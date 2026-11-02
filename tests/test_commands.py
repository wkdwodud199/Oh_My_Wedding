from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from wedding_assistant.commands import Commands
from wedding_assistant.engine import Engine
from wedding_assistant.models import Task
from wedding_assistant.sheets import WriteUncertainError
from wedding_assistant.storage import JsonRepository, State


class MemoryMessenger:
    def __init__(self, fail_count=0):
        self.fail_count = fail_count
        self.messages = []

    def send(self, text):
        if self.fail_count:
            self.fail_count -= 1
            raise RuntimeError("simulated delivery outage")
        self.messages.append(text)


class ExampleReport:
    signature = "example-report-signature"

    def as_dict(self):
        return {"summary": "예제 조사 결과", "sources": [{"url": "https://example.invalid/source"}]}

    def text(self):
        return "예제 조사 결과 https://example.invalid/source"


class ExampleResearcher:
    def research(self, category, region, budget):
        return ExampleReport()


class CrashAfterSaveRepository(JsonRepository):
    def __init__(self, path):
        super().__init__(path)
        self.fail = True

    def update_task(self, task_id, changes, expected=None):
        saved = super().update_task(task_id, changes, expected)
        if self.fail:
            self.fail = False
            raise RuntimeError("process interrupted after saving")
        return saved


class ReadbackFailureRepository(JsonRepository):
    def update_task(self, task_id, changes, expected=None):
        super().update_task(task_id, changes, expected)
        raise WriteUncertainError("write succeeded but readback was interrupted")


class CommandsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.json"
        tasks = [
            Task("W001", "스튜디오", "스튜디오 계약", deadline="2027-04", region="서울", research_enabled=True),
            Task("W002", "촬영", "웨딩 촬영", deadline="2027-05-20", depends_on="W001"),
        ]
        self.path.write_text(json.dumps([t.to_dict() for t in tasks], ensure_ascii=False), encoding="utf-8")
        self.repo = JsonRepository(str(self.path))
        self.state = State(":memory:")
        self.addCleanup(self.state.close)
        self.messenger = MemoryMessenger()
        self.tz = timezone(timedelta(hours=9))
        self.now = datetime(2027, 4, 1, 20, tzinfo=self.tz)
        settings = SimpleNamespace(
            mode="demo", tz=self.tz, digest_hour=20, quiet_end_hour=21,
            research_interval_days=7, max_research_per_run=3, reminder_days=(30, 14, 7, 3, 1, 0),
        )
        self.engine = Engine(settings, self.repo, self.state, ExampleResearcher(), self.messenger)
        self.commands = Commands(self.engine)

    def send(self, update_id, text):
        handled = self.commands.handle(update_id, text, "공동", self.now)
        errors = self.engine.flush(self.now)
        return handled, errors

    def read_logs(self, kind):
        path = self.path.with_name(f"{kind}.jsonl")
        return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_quoted_multiple_field_update_and_empty_value(self):
        self.send("1", '/edit W001 업체="예시 스튜디오" 상태=계약완료 메모="상담 시간 변경" 조사여부=아니오')
        task = self.repo.get_tasks()[0]
        self.assertEqual(task.vendor, "예시 스튜디오")
        self.assertEqual(task.notes, "상담 시간 변경")
        self.assertFalse(task.research_enabled)
        self.assertEqual(task.status, "계약완료")
        self.assertIn("로컬 예제 수정 완료", self.messenger.messages[0])
        self.assertEqual(len(self.read_logs("changes")), 1)
        self.send("2", '/edit W001 메모=""')
        self.assertEqual(self.repo.get_tasks()[0].notes, "")

    def test_unknown_column_and_invalid_date_never_write(self):
        original = self.path.read_bytes()
        commands = [
            "/edit W001 없는열=값", "/edit W001 마감일=4월", "/edit W001 업무ID=새ID",
            "/edit W001 상태=완료 상태=미정", "/edit W001 선행업무=W002",
            '/edit W001 업체="닫지 않은 따옴표',
        ]
        for index, command in enumerate(commands):
            self.send(f"invalid-{index}", command)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.read_logs("changes"), [])
        self.assertTrue(all("반영하지 못했습니다" in message for message in self.messenger.messages))

    def test_same_update_replay_does_not_change_or_notify_twice(self):
        self.send("same-id", "/edit W001 상태=계약완료")
        saved = self.path.read_bytes()
        self.send("same-id", "/edit W001 상태=미정")
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(len(self.read_logs("changes")), 1)
        self.assertEqual(len(self.messenger.messages), 1)

    def test_interrupted_edit_recovers_audit_and_message_without_second_write(self):
        crashing = CrashAfterSaveRepository(str(self.path))
        self.engine.repository = crashing
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.commands.handle("crash", "/edit W001 상태=계약완료", "공동", self.now)
        saved = self.path.read_bytes()
        self.assertFalse(self.state.get("command:crash"))
        self.assertIsNotNone(self.state.get("edit-intent:crash"))
        self.send("crash", "/edit W001 상태=계약완료")
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(len(self.read_logs("changes")), 1)
        self.assertEqual(len(self.messenger.messages), 1)
        self.assertTrue(self.state.get("command:crash"))

    def test_manual_conflicting_edit_is_preserved(self):
        expected = self.repo.get_tasks()[0]
        self.state.put("edit-intent:conflict", {
            "task_id": "W001", "expected": expected.to_dict(), "actor": "공동",
            "changes": {"status": {"before": "미정", "after": "계약완료"}},
        })
        self.repo.update_task("W001", {"owner": "직접 수정한 담당"})
        saved = self.path.read_bytes()
        self.send("conflict", "/edit W001 상태=계약완료")
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertIn("반영하지 못했습니다", self.messenger.messages[0])
        self.assertEqual(self.read_logs("changes"), [])

    def test_uncertain_readback_retries_without_false_failure_or_second_write(self):
        self.engine.repository = ReadbackFailureRepository(str(self.path))
        with self.assertRaises(WriteUncertainError):
            self.commands.handle("readback", "/edit W001 상태=계약완료", "공동", self.now)
        saved = self.path.read_bytes()
        self.assertFalse(self.state.get("command:readback"))
        self.assertEqual(self.state.pending(), [])
        self.send("readback", "/edit W001 상태=계약완료")
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(len(self.read_logs("changes")), 1)
        self.assertEqual(len(self.messenger.messages), 1)
        self.assertIn("수정 완료", self.messenger.messages[0])

    def test_schedule_and_ordinary_conversation(self):
        original = self.path.read_bytes()
        handled, _ = self.send("chat", "스튜디오는 다음에 정하자")
        self.assertFalse(handled)
        self.assertEqual(self.messenger.messages, [])
        self.send("schedule", "/schedule")
        self.assertIn("2027-04-30", self.messenger.messages[0])
        self.assertLess(self.messenger.messages[0].find("W001"), self.messenger.messages[0].find("W002"))
        self.assertEqual(self.path.read_bytes(), original)

    def test_change_delivery_retry_does_not_duplicate_log(self):
        self.messenger.fail_count = 1
        _, errors = self.send("retry", "/edit W001 상태=계약완료")
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(self.read_logs("changes")), 1)
        saved = self.path.read_bytes()
        self.assertEqual(self.engine.flush(self.now), [])
        self.assertEqual(len(self.read_logs("changes")), 1)
        self.assertEqual(len(self.messenger.messages), 1)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_research_delivery_retry_does_not_duplicate_source_log(self):
        self.messenger.fail_count = 1
        self.commands.handle("research", "/research W001", "공동", self.now)
        self.assertTrue(self.engine.flush(self.now))
        self.assertEqual(len(self.read_logs("research")), 1)
        self.assertEqual(self.engine.flush(self.now), [])
        self.assertEqual(len(self.read_logs("research")), 1)
        sources = self.read_logs("research")[0]["sources"]
        self.assertEqual(sources[0]["url"], "https://example.invalid/source")
        self.assertEqual(len(self.messenger.messages), 2)

    def test_noop_has_no_change_log(self):
        original = self.path.read_bytes()
        self.send("noop", "/edit W001 상태=미정")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.read_logs("changes"), [])
        self.assertIn("변경하지 않았습니다", self.messenger.messages[0])


if __name__ == "__main__":
    unittest.main()

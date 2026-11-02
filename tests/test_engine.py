import json
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from wedding_assistant.config import Settings
from wedding_assistant.engine import Engine, reminder_bucket
from wedding_assistant.models import Task, parse_deadline
from wedding_assistant.research import ResearchReport, Source
from wedding_assistant.storage import JsonRepository, State


class FakeResearch:
    def __init__(self):
        self.calls = []
        self.failures_remaining = 0
        self.version = "첫 근거"

    def research(self, topic, region, budget=""):
        self.calls.append((topic, region, budget))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("temporary search error")
        return ResearchReport(topic, region, "검증용 검색 결과", [
            Source("가상 테스트 출처", "https://example.invalid/test",
                   f"{self.version} / {topic} / {region} / {budget}",
                   checked_at=str(len(self.calls))),
        ])


class FakeMessenger:
    def __init__(self, trace):
        self.trace = trace
        self.messages = []
        self.failures_remaining = 0
        self.fail_on_call = None
        self.calls = 0

    def send(self, text):
        self.calls += 1
        if self.failures_remaining or self.calls == self.fail_on_call:
            self.failures_remaining = max(0, self.failures_remaining - 1)
            raise RuntimeError("temporary send error")
        self.trace.append("send")
        self.messages.append(text)


class TracedRepository(JsonRepository):
    def __init__(self, path, trace):
        super().__init__(path)
        self.trace = trace
        self.fail_result_writes = 0
        self.fail_change_writes = 0

    def append_result(self, event_id, task, report):
        if self.fail_result_writes:
            self.fail_result_writes -= 1
            raise RuntimeError("temporary sheet result error")
        super().append_result(event_id, task, report)
        self.trace.append("result_saved")

    def append_change(self, event_id, task_id, actor, changes):
        if self.fail_change_writes:
            self.fail_change_writes -= 1
            raise RuntimeError("temporary sheet audit error")
        super().append_change(event_id, task_id, actor, changes)
        self.trace.append("change_saved")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace = []
        self.settings = Settings()
        self.repository = TracedRepository(str(self.root / "tasks.json"), self.trace)
        self.state = State(":memory:")
        self.addCleanup(self.state.close)
        self.researcher = FakeResearch()
        self.messenger = FakeMessenger(self.trace)
        self.engine = Engine(self.settings, self.repository, self.state, self.researcher, self.messenger)
        self.write_tasks()

    def stamp(self, value="2027-04-01", hour=20):
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), self.settings.tz).replace(hour=hour)

    def task(self, **changes):
        return Task.from_dict({"id": "T1", "category": "스튜디오", "title": "촬영 업체 계약", **changes})

    def write_tasks(self, *tasks):
        self.repository.path.write_text(json.dumps([task.to_dict() for task in tasks], ensure_ascii=False), encoding="utf-8")

    def records(self, kind):
        path = self.root / f"{kind}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_reminder_threshold_catch_up_does_not_send_every_missed_threshold(self):
        self.write_tasks(self.task(deadline="2027-04-20"))
        self.engine.run_once(self.stamp("2027-04-08"))  # First launch, only 12 days remain.
        self.assertEqual(1, len(self.messenger.messages))
        self.assertIn("12일 남았습니다", self.messenger.messages[0])
        self.assertTrue(self.state.has_event("reminder:T1:2027-04-20:before-14"))
        self.engine.run_once(self.stamp("2027-04-10"))
        self.assertEqual(1, len(self.messenger.messages))
        self.engine.run_once(self.stamp("2027-04-13"))
        self.assertEqual(2, len(self.messenger.messages))
        self.assertIn("7일 남았습니다", self.messenger.messages[-1])

    def test_today_then_overdue_only_once_per_seven_day_bucket(self):
        self.write_tasks(self.task(deadline="2027-04-01"))
        for day in ["2027-04-01", "2027-04-02", "2027-04-03", "2027-04-08", "2027-04-09"]:
            self.engine.run_once(self.stamp(day))
        self.assertEqual(3, len(self.messenger.messages))
        self.assertIn("오늘이 마감", self.messenger.messages[0])
        self.assertIn("1일 지났습니다", self.messenger.messages[1])
        self.assertIn("8일 지났습니다", self.messenger.messages[2])

    def test_bucket_boundaries(self):
        thresholds = self.settings.reminder_days
        self.assertIsNone(reminder_bucket(31, thresholds))
        for days, expected in [(30, "before-30"), (15, "before-30"), (14, "before-14"),
                               (8, "before-14"), (7, "before-7"), (3, "before-3"),
                               (1, "before-1"), (0, "before-0"), (-1, "overdue-0"),
                               (-7, "overdue-0"), (-8, "overdue-1")]:
            with self.subTest(days=days):
                self.assertEqual(expected, reminder_bucket(days, thresholds))

    def test_month_target_uses_real_month_end_including_leap_year(self):
        self.assertEqual(date(2027, 2, 28), parse_deadline("2027-02"))
        self.assertEqual(date(2028, 2, 29), parse_deadline("2028-02"))
        self.write_tasks(self.task(deadline="2028-02"))
        self.engine.run_once(self.stamp("2028-02-01"))
        self.assertIn("2028-02-29", self.messenger.messages[0])
        self.assertIn("마지막 날로 계산", self.messenger.messages[0])

    def test_closed_and_held_tasks_neither_research_nor_remind(self):
        tasks = [self.task(id=f"T{i}", status=status, region="서울", research_enabled=True, deadline="2027-04-01")
                 for i, status in enumerate(["완료", "계약완료", "예약완료", "취소", "보류"])]
        self.write_tasks(*tasks)
        self.engine.run_once(self.stamp())
        self.assertEqual([], self.researcher.calls)
        self.assertEqual([], self.messenger.messages)
        self.assertEqual([], self.state.pending())

    def test_same_source_evidence_rechecked_without_duplicate_record_or_message(self):
        self.write_tasks(self.task(region="서울", research_enabled=True))
        self.engine.run_once(self.stamp())
        self.engine.run_once(self.stamp("2027-04-02"))
        self.engine.run_once(self.stamp("2027-04-08"))
        self.assertEqual(2, len(self.researcher.calls))
        self.assertEqual(1, len(self.records("research")))
        self.assertEqual(1, len(self.messenger.messages))
        self.researcher.version = "가격이 달라진 근거"
        self.engine.run_once(self.stamp("2027-04-15"))
        self.assertEqual(2, len(self.records("research")))
        self.assertEqual(2, len(self.messenger.messages))

    def test_region_and_budget_changes_trigger_immediate_new_research(self):
        self.write_tasks(self.task(region="서울", budget="100만원", research_enabled=True))
        now = self.stamp()
        self.engine.run_once(now)
        self.repository.update_task("T1", {"region": "인천"})
        self.engine.run_once(now)
        self.repository.update_task("T1", {"budget": "200만원"})
        self.engine.run_once(now)
        self.assertEqual([("스튜디오", "서울", "100만원"), ("스튜디오", "인천", "100만원"),
                          ("스튜디오", "인천", "200만원")], self.researcher.calls)
        self.assertEqual(3, len(self.records("research")))

    def test_sheet_result_is_written_before_research_notification(self):
        self.write_tasks(self.task(region="서울", research_enabled=True))
        self.repository.fail_result_writes = 1
        self.assertEqual(1, len(self.engine.run_once(self.stamp())))
        self.assertEqual([], self.messenger.messages)
        self.assertEqual(0, self.state.pending()[0]["sheet_done"])
        self.assertEqual([], self.engine.run_once(self.stamp()))
        self.assertEqual(["result_saved", "send"], self.trace)
        self.assertEqual(1, len(self.researcher.calls))
        self.assertEqual(1, len(self.records("research")))

    def test_audit_write_precedes_change_notification_and_retries(self):
        self.state.enqueue("change:test", {"kind": "change", "task_id": "T1", "actor": "테스트",
                                          "changes": {"status": "완료"}, "text": "수정 완료"})
        self.repository.fail_change_writes = 1
        self.assertEqual(1, len(self.engine.flush(self.stamp())))
        self.assertEqual([], self.messenger.messages)
        self.assertEqual([], self.engine.flush(self.stamp()))
        self.assertEqual(["change_saved", "send"], self.trace)
        self.assertEqual(1, len(self.records("changes")))

    def test_failed_delivery_survives_state_reopen_without_duplicate_sheet_row(self):
        state_file = str(self.root / "durable.sqlite3")
        original = State(state_file)
        self.engine.state = original
        self.write_tasks(self.task(region="서울", research_enabled=True))
        self.messenger.failures_remaining = 1
        self.engine.run_once(self.stamp())
        self.assertEqual(1, original.pending()[0]["sheet_done"])
        original.close()
        restored = State(state_file)
        self.addCleanup(restored.close)
        self.engine.state = restored
        self.assertEqual([], self.engine.run_once(self.stamp()))
        self.assertEqual([], restored.pending())
        self.assertEqual(1, len(self.records("research")))
        self.assertEqual(1, len(self.messenger.messages))
        self.assertEqual(1, len(self.researcher.calls))

    def test_multipart_retry_does_not_repeat_already_sent_parts(self):
        text = "가" * 6500
        self.state.enqueue("notice:multipart", {"kind": "notice", "text": text})
        self.messenger.fail_on_call = 2
        self.engine.flush(self.stamp())
        self.assertEqual(1, self.state.pending()[0]["sent_parts"])
        self.assertEqual(1, len(self.messenger.messages))
        self.engine.flush(self.stamp())
        self.assertEqual(3, len(self.messenger.messages))
        self.assertEqual(text, "".join(self.messenger.messages))
        self.assertEqual([], self.state.pending())

    def test_completion_suppresses_queued_research_and_reminder(self):
        task = self.task(region="서울", research_enabled=True, deadline="2027-04-05")
        self.write_tasks(task)
        now = self.stamp()
        self.engine.schedule_reminders([task], now)
        self.engine.research_task(task, now)
        self.assertEqual(2, len(self.state.pending()))
        self.repository.update_task("T1", {"status": "완료"})
        self.engine.flush(now)
        self.assertEqual([], self.state.pending())
        self.assertEqual([], self.messenger.messages)
        self.assertEqual([], self.records("research"))

    def test_changed_deadline_suppresses_queued_old_reminder(self):
        task = self.task(deadline="2027-04-05")
        self.write_tasks(task)
        self.engine.schedule_reminders([task], self.stamp())
        self.repository.update_task("T1", {"deadline": "2027-07-01"})
        self.engine.flush(self.stamp())
        self.assertEqual([], self.messenger.messages)
        self.assertEqual([], self.state.pending())

    def test_old_threshold_reminder_is_replaced_after_long_delivery_outage(self):
        task = self.task(deadline="2027-04-20")
        self.write_tasks(task)
        self.engine.schedule_reminders([task], self.stamp("2027-04-01"))
        self.engine.run_once(self.stamp("2027-04-19"))
        self.assertEqual(1, len(self.messenger.messages))
        self.assertIn("1일 남았습니다", self.messenger.messages[0])
        self.assertEqual([], self.state.pending())

    def test_changed_research_preferences_discard_queued_old_research(self):
        task = self.task(region="서울", research_enabled=True)
        self.write_tasks(task)
        self.engine.research_task(task, self.stamp())
        self.repository.update_task("T1", {"region": "인천"})
        self.engine.flush(self.stamp())
        self.assertEqual([], self.messenger.messages)
        self.assertEqual([], self.records("research"))
        self.assertEqual([], self.state.pending())

    def test_quiet_hours_defer_automatic_work_but_allow_manual_research(self):
        task = self.task(region="서울", research_enabled=True, deadline="2027-04-02")
        self.write_tasks(task)
        self.engine.run_once(self.stamp(hour=8))
        self.assertEqual([], self.researcher.calls)
        self.assertEqual([], self.messenger.messages)
        self.engine.research_task(task, self.stamp(hour=8), force=True)
        self.engine.flush(self.stamp(hour=8))
        self.assertEqual(1, len(self.messenger.messages))
        self.engine.schedule_reminders([task], self.stamp(hour=8))
        self.engine.flush(self.stamp(hour=8))
        self.assertEqual(1, len(self.messenger.messages))
        self.engine.flush(self.stamp(hour=20))
        self.assertEqual(2, len(self.messenger.messages))

    def test_no_region_requests_input_without_searching(self):
        self.write_tasks(self.task(research_enabled=True))
        self.engine.run_once(self.stamp())
        self.engine.run_once(self.stamp())
        self.assertEqual([], self.researcher.calls)
        self.assertEqual(1, len(self.messenger.messages))
        self.assertIn("조사 지역을 먼저 입력", self.messenger.messages[0])

    def test_search_failure_retries_after_cooldown_and_does_not_skip_other_task(self):
        self.settings.digest_hour, self.settings.quiet_end_hour = 0, 24
        self.write_tasks(self.task(region="서울", research_enabled=True),
                         self.task(id="T2", category="메이크업", region="서울", research_enabled=True))
        self.researcher.failures_remaining = 1
        now = self.stamp()
        self.engine.run_once(now)
        self.assertEqual(2, len(self.researcher.calls))
        self.assertEqual(1, len(self.records("research")))
        self.engine.run_once(now + timedelta(minutes=30))
        self.assertEqual(2, len(self.researcher.calls))
        self.engine.run_once(now + timedelta(minutes=61))
        self.assertEqual(3, len(self.researcher.calls))
        self.assertEqual(2, len(self.records("research")))

    def test_appointment_fallback_uses_configured_local_date(self):
        task = self.task(appointment="2027-04-01T18:00:00+00:00")
        self.write_tasks(task)
        self.engine.run_once(self.stamp())
        self.assertIn("목표일 2027-04-02", self.messenger.messages[0])
        self.assertIn("1일 남았습니다", self.messenger.messages[0])

    def test_missing_region_tasks_do_not_consume_the_search_budget(self):
        self.settings.max_research_per_run = 1
        self.write_tasks(self.task(id="T1", research_enabled=True),
                         self.task(id="T2", research_enabled=True),
                         self.task(id="T3", research_enabled=True, region="서울"))
        self.engine.run_once(self.stamp())
        self.assertEqual([("스튜디오", "서울", "")], self.researcher.calls)
        self.assertEqual(1, len(self.records("research")))

    def test_removed_task_discards_pending_research_and_reminder(self):
        task = self.task(region="서울", research_enabled=True, deadline="2027-04-05")
        self.write_tasks(task)
        self.engine.schedule_reminders([task], self.stamp())
        self.engine.research_task(task, self.stamp())
        self.write_tasks()
        self.assertEqual([], self.engine.flush(self.stamp()))
        self.assertEqual([], self.state.pending())
        self.assertEqual([], self.messenger.messages)

    def test_evidence_a_to_b_to_a_records_each_change(self):
        self.write_tasks(self.task(region="서울", research_enabled=True))
        for version, day in [("가격 A", "2027-04-01"), ("가격 B", "2027-04-08"), ("가격 A", "2027-04-15")]:
            self.researcher.version = version
            self.engine.run_once(self.stamp(day))
        self.assertEqual(3, len(self.records("research")))
        self.assertEqual(3, len(self.messenger.messages))
        self.assertEqual(3, len({record["event_id"] for record in self.records("research")}))

    def test_retry_next_day_uses_current_remaining_days_in_same_bucket(self):
        self.write_tasks(self.task(deadline="2027-04-20"))
        self.messenger.failures_remaining = 1
        self.engine.run_once(self.stamp("2027-04-01"))
        self.assertEqual([], self.messenger.messages)
        self.engine.run_once(self.stamp("2027-04-02"))
        self.assertEqual(1, len(self.messenger.messages))
        self.assertIn("18일 남았습니다", self.messenger.messages[0])
        self.assertNotIn("19일 남았습니다", self.messenger.messages[0])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import re
import unittest

from wedding_assistant.models import TASK_HEADERS, Task
from wedding_assistant.sheets import (
    CHANGE_HEADERS, CHANGE_SHEET, RESULT_HEADERS, RESULT_SHEET, TASK_SHEET,
    GoogleSheetsRepository, WriteUncertainError,
)


class Request:
    def __init__(self, action):
        self.action = action

    def execute(self):
        return self.action()


class FakeSheets:
    def __init__(self, tasks=None):
        tasks = tasks or [Task("studio", "스튜디오", "촬영 업체 계약", research_enabled=True)]
        self.tables = {
            TASK_SHEET: [list(TASK_HEADERS)] + [[task.to_dict()[f] for f in TASK_HEADERS.values()] for task in tasks],
            RESULT_SHEET: [list(RESULT_HEADERS)],
            CHANGE_SHEET: [list(CHANGE_HEADERS)],
        }
        self.row_counts = {TASK_SHEET: 1000, RESULT_SHEET: 1000, CHANGE_SHEET: 1000}
        self.calls = []
        self.after_write = None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    @staticmethod
    def parse_range(value):
        match = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", value)
        if not match:
            raise AssertionError(value)
        tab, col, row, last_col, last_row = match.groups()

        def column(s):
            result = 0
            for c in s:
                result = result * 26 + ord(c) - 64
            return result - 1

        return tab, column(col), int(row) - 1, column(last_col or col), int(last_row or row) - 1

    def get(self, **kwargs):
        def run():
            self.calls.append(("get", copy.deepcopy(kwargs)))
            if "range" not in kwargs:
                return {"sheets": [{"properties": {
                    "title": tab, "gridProperties": {"rowCount": self.row_counts[tab], "columnCount": 26}
                }} for tab in self.tables]}
            tab, left, top, right, bottom = self.parse_range(kwargs["range"])
            result = []
            for row in self.tables[tab][top:bottom + 1]:
                out = copy.deepcopy(row[left:right + 1])
                if kwargs.get("valueRenderOption") == "FORMATTED_VALUE":
                    out = ["TRUE" if v is True else "FALSE" if v is False else str(v) if v is not None else "" for v in out]
                while out and out[-1] in (None, ""):
                    out.pop()
                result.append(out)
            while result and not result[-1]:
                result.pop()
            return {"values": result}
        return Request(run)

    def _put(self, target, values):
        tab, left, top, _, _ = self.parse_range(target)
        for offset, row in enumerate(values):
            while len(self.tables[tab]) <= top + offset:
                self.tables[tab].append([])
            dest = self.tables[tab][top + offset]
            dest.extend([""] * max(0, left + len(row) - len(dest)))
            dest[left:left + len(row)] = copy.deepcopy(row)

    def batchUpdate(self, **kwargs):
        def run():
            self.calls.append(("batchUpdate", copy.deepcopy(kwargs)))
            for update in kwargs["body"]["data"]:
                self._put(update["range"], update["values"])
            if self.after_write:
                self.after_write(self)
            return {}
        return Request(run)

    def update(self, **kwargs):
        def run():
            self.calls.append(("update", copy.deepcopy(kwargs)))
            self._put(kwargs["range"], kwargs["body"]["values"])
            if self.after_write:
                self.after_write(self)
            return {}
        return Request(run)

    @property
    def writes(self):
        return [(method, kwargs) for method, kwargs in self.calls if method in {"update", "batchUpdate"}]


class SheetsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        self.repo = GoogleSheetsRepository("demo-id", allow_writes=True, service=self.fake)

    def test_reads_exact_tab_and_bounded_range(self):
        tasks = self.repo.get_tasks()
        self.assertEqual(tasks[0].id, "studio")
        self.assertTrue(tasks[0].research_enabled)
        self.assertEqual(self.fake.calls[-1][1]["range"], "'준비업무'!A1:N1000")
        self.assertEqual(self.fake.writes, [])

    def test_disabled_writes_make_no_api_calls(self):
        repo = GoogleSheetsRepository("demo-id", service=self.fake)
        task = Task("studio", "스튜디오", "업체 결정")
        for action in [
            lambda: repo.update_task("studio", {"status": "완료"}),
            lambda: repo.append_result("e1", task, {}),
            lambda: repo.append_change("e2", "studio", "공동", {}),
        ]:
            with self.assertRaises(PermissionError):
                action()
        self.assertEqual(self.fake.calls, [])

    def test_missing_tab_or_schema_is_actionable(self):
        del self.fake.tables[TASK_SHEET]
        with self.assertRaisesRegex(ValueError, "준비업무.*탭이 없습니다"):
            self.repo.get_tasks()
        self.fake.tables[TASK_SHEET] = [["아무 표"]]
        with self.assertRaisesRegex(ValueError, "첫 행의 열 이름"):
            self.repo.get_tasks()
        self.assertEqual(self.fake.writes, [])

    def test_duplicate_id_rejected(self):
        self.fake.tables[TASK_SHEET].append(copy.deepcopy(self.fake.tables[TASK_SHEET][1]))
        with self.assertRaisesRegex(ValueError, "중복 업무ID"):
            self.repo.get_tasks()

    def test_update_resolves_moved_row_and_writes_only_changed_cells(self):
        old = self.repo.get_tasks()[0]
        self.fake.tables[TASK_SHEET].insert(1, ["makeup", "메이크업", "메이크업 계약", "미정"])
        updated = self.repo.update_task("studio", {"status": "계약완료", "vendor": "예시 업체"}, expected=old)
        self.assertEqual(updated.status, "계약완료")
        self.assertTrue(updated.updated_at.endswith("+00:00"))
        body = self.fake.writes[0][1]["body"]
        self.assertEqual(body["valueInputOption"], "RAW")
        self.assertEqual({v["range"] for v in body["data"]}, {"'준비업무'!D3", "'준비업무'!J3", "'준비업무'!N3"})
        self.assertEqual(self.fake.tables[TASK_SHEET][1][3], "미정")

    def test_reordered_headers_are_resolved_by_name(self):
        for row in self.fake.tables[TASK_SHEET]:
            row[0], row[3] = row[3], row[0]
        result = self.repo.update_task("studio", {"status": "계약완료"})
        self.assertEqual(result.status, "계약완료")
        self.assertEqual(self.fake.writes[0][1]["body"]["data"][0]["range"], "'준비업무'!A2")

    def test_stale_expected_blocks_write(self):
        old = self.repo.get_tasks()[0]
        self.fake.tables[TASK_SHEET][1][12] = "직접 수정한 메모"
        with self.assertRaisesRegex(ValueError, "요청 이후 바뀌었습니다"):
            self.repo.update_task("studio", {"status": "완료"}, expected=old)
        self.assertEqual(self.fake.writes, [])

    def test_noop_does_not_touch_updated_at(self):
        old = self.repo.get_tasks()[0]
        self.assertEqual(self.repo.update_task("studio", {}).to_dict(), old.to_dict())
        self.assertEqual(self.repo.update_task("studio", {"status": "미정"}).to_dict(), old.to_dict())
        self.assertEqual(self.fake.writes, [])

    def test_validation_happens_before_write(self):
        for changes in [
            {"id": "new"}, {"status": "알수없음"}, {"deadline": "4월"},
            {"depends_on": "missing"}, {"budget": 1000},
        ]:
            with self.assertRaises(ValueError):
                self.repo.update_task("studio", changes)
        self.assertEqual(self.fake.writes, [])

    def test_readback_mismatch_is_reported_without_second_write(self):
        def interfere(fake):
            fake.tables[TASK_SHEET][1][12] = "동시 수정"
        self.fake.after_write = interfere
        with self.assertRaisesRegex(WriteUncertainError, "수정 요청은 전송됐지만"):
            self.repo.update_task("studio", {"status": "완료"})
        self.assertEqual(len(self.fake.writes), 1)

    def test_post_write_validation_error_is_retryable_uncertain_result(self):
        def invalidate_header(fake):
            fake.tables[TASK_SHEET][0][0] = "직접 바뀐 헤더"
        self.fake.after_write = invalidate_header
        with self.assertRaises(WriteUncertainError) as caught:
            self.repo.update_task("studio", {"status": "완료"})
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        self.assertEqual(len(self.fake.writes), 1)

    def test_record_readback_failure_is_retryable_uncertain_result(self):
        def remove_tab(fake):
            del fake.tables[CHANGE_SHEET]
        self.fake.after_write = remove_tab
        with self.assertRaises(WriteUncertainError):
            self.repo.append_change("c1", "studio", "공동", {})
        self.assertEqual(len(self.fake.writes), 1)

    def test_append_is_deduplicated_and_raw(self):
        task = self.repo.get_tasks()[0]
        report = {"summary": "=예시 요약", "sources": [{"url": "https://example.invalid/review"}]}
        self.repo.append_result("r1", task, report)
        self.repo.append_result("r1", task, report)
        self.assertEqual(len(self.fake.writes), 1)
        method, request = self.fake.writes[0]
        self.assertEqual(method, "update")
        self.assertEqual(request["range"], "'조사결과'!A2:G2")
        self.assertEqual(request["valueInputOption"], "RAW")
        self.assertEqual(self.fake.tables[RESULT_SHEET][1][5], "=예시 요약")
        self.repo.append_change("c1", task.id, "공동", {"status": {"before": "미정", "after": "완료"}})
        self.repo.append_change("c1", task.id, "공동", {})
        self.assertEqual(len(self.fake.writes), 2)

    def test_full_record_table_and_oversized_grid_fail_explicitly(self):
        self.fake.row_counts[CHANGE_SHEET] = 1
        with self.assertRaisesRegex(ValueError, "기록 공간이 찼습니다"):
            self.repo.append_change("c1", "studio", "공동", {})
        self.fake.row_counts[TASK_SHEET] = 1002
        with self.assertRaisesRegex(ValueError, "누락하지 않도록 중단"):
            self.repo.get_tasks()
        self.assertEqual(self.fake.writes, [])


if __name__ == "__main__":
    unittest.main()

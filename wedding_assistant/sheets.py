"""Small, explicit Google Sheets tables; never infer or migrate the user's layout.

This adapter assumes one worker. Sheets has no conditional value-update API, so
the fresh read detects stale requests but cannot lock out a simultaneous UI edit.
Readback detects mismatches and deliberately does not roll back other edits.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .models import EDITABLE_FIELDS, TASK_HEADERS, Task, validate_tasks


TASK_SHEET = "준비업무"
RESULT_SHEET = "조사결과"
CHANGE_SHEET = "변경기록"
RESULT_HEADERS = ["기록ID", "업무ID", "조회일", "영역", "지역", "요약", "출처JSON"]
CHANGE_HEADERS = ["기록ID", "시각", "업무ID", "요청자", "변경JSON"]
SCHEMAS = {
    TASK_SHEET: {"headers": list(TASK_HEADERS), "max_rows": 1001},
    RESULT_SHEET: {"headers": RESULT_HEADERS, "max_rows": 5001},
    CHANGE_SHEET: {"headers": CHANGE_HEADERS, "max_rows": 5001},
}


class WriteUncertainError(RuntimeError):
    """A write was sent but readback could not establish the resulting state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _a1(tab: str, cells: str) -> str:
    return "'" + tab.replace("'", "''") + "'!" + cells


def _column(index: int) -> str:
    """Zero-based column number to A1 column name."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class GoogleSheetsRepository:
    def __init__(
        self,
        spreadsheet_id: str,
        credentials_file: str = "",
        allow_writes: bool = False,
        service: Any = None,
    ):
        if not spreadsheet_id.strip() or "/" in spreadsheet_id:
            raise ValueError("SPREADSHEET_ID에 URL이 아닌 Google Sheets 파일 ID를 넣어 주세요.")
        self.spreadsheet_id = spreadsheet_id
        self.allow_writes = allow_writes
        if service is None:
            import google.auth
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            scope = "https://www.googleapis.com/auth/spreadsheets"
            scopes = [scope if allow_writes else scope + ".readonly"]
            if credentials_file:
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_file, scopes=scopes
                )
            else:
                credentials, _ = google.auth.default(scopes=scopes)
            service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self.service = service

    def _require_writes(self) -> None:
        if not self.allow_writes:
            raise PermissionError(
                "시트 쓰기가 꺼져 있습니다. 실제 반영을 정한 뒤 SHEETS_WRITE_ENABLED=true로 설정해 주세요."
            )

    def _read_table(self, tab: str) -> tuple[list[str], list[list], int]:
        schema = SCHEMAS[tab]
        expected_headers = schema["headers"]
        metadata = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(title,gridProperties(rowCount,columnCount)))",
        ).execute()
        properties = next(
            (s.get("properties", {}) for s in metadata.get("sheets", [])
             if s.get("properties", {}).get("title") == tab),
            None,
        )
        if properties is None:
            raise ValueError(
                f"'{tab}' 탭이 없습니다. 시트 준비 안내에 따라 탭과 첫 행을 직접 준비해 주세요. "
                f"필수 열: {', '.join(expected_headers)}. 기존 탭은 자동 변경하지 않습니다."
            )
        grid = properties.get("gridProperties", {})
        row_count = grid.get("rowCount", 0)
        if row_count < 1 or grid.get("columnCount", 0) < len(expected_headers):
            raise ValueError(f"'{tab}' 탭에 최소 1행과 {len(expected_headers)}개 열이 필요합니다.")
        if row_count > schema["max_rows"]:
            raise ValueError(
                f"'{tab}' 탭의 격자 행수 {row_count}가 지원 한도 {schema['max_rows']}를 넘습니다. "
                "끝부분을 누락하지 않도록 중단했습니다. 빈 끝행을 정리하거나 기록을 보관한 뒤 "
                "탭 크기를 줄여 주세요. 더 큰 표는 읽기 한도 확장 후 사용할 수 있습니다."
            )
        bound = min(row_count, schema["max_rows"])
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=_a1(tab, f"A1:{_column(len(expected_headers) - 1)}{bound}"),
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
        values = result.get("values", [])
        headers = values[0] if values else []
        if len(headers) != len(expected_headers) or set(headers) != set(expected_headers):
            raise ValueError(
                f"'{tab}' 첫 행의 열 이름이 맞지 않습니다. "
                f"필수 열을 각각 한 번씩 넣어 주세요: {', '.join(expected_headers)}. "
                "기존 표를 추측하여 읽거나 수정하지 않습니다."
            )
        if len(values) > bound:
            raise ValueError(f"'{tab}' 응답이 읽기 범위를 넘었습니다. 표 크기를 확인해 주세요.")
        return headers, values[1:], bound

    def _task_rows(self) -> tuple[list[Task], dict[str, int], list[str]]:
        headers, rows, _ = self._read_table(TASK_SHEET)
        tasks: list[Task] = []
        positions: dict[str, int] = {}
        for row_number, row in enumerate(rows, start=2):
            if not any(value not in (None, "") for value in row):
                continue
            if len(row) > len(headers):
                raise ValueError(f"'{TASK_SHEET}' {row_number}행에 예상보다 많은 값이 있습니다.")
            data = {
                TASK_HEADERS[header]: str(row[index]) if index < len(row) and row[index] is not None else ""
                for index, header in enumerate(headers)
            }
            try:
                task = Task.from_dict(data)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"'{TASK_SHEET}' {row_number}행을 확인해 주세요: {exc}") from exc
            tasks.append(task)
            positions[task.id] = row_number
        return validate_tasks(tasks), positions, headers

    def get_tasks(self) -> list[Task]:
        tasks, _, _ = self._task_rows()
        return tasks

    def update_task(
        self, task_id: str, changes: dict[str, object], expected: Task | None = None
    ) -> Task:
        self._require_writes()
        unknown = set(changes) - EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"수정할 수 없는 필드: {', '.join(sorted(unknown))}")
        if any(field != "research_enabled" and not isinstance(value, str) for field, value in changes.items()):
            raise ValueError("조사여부 외의 수정 값은 문자열로 전달해 주세요.")
        tasks, positions, headers = self._task_rows()
        latest = next((task for task in tasks if task.id == task_id), None)
        if latest is None:
            raise ValueError(f"업무ID '{task_id}'를 찾을 수 없습니다. 목록에서 ID를 다시 확인해 주세요.")
        if expected is not None and latest.to_dict() != expected.to_dict():
            raise ValueError("시트 내용이 요청 이후 바뀌었습니다. 최신 내용을 확인하고 다시 요청해 주세요.")
        updated = Task.from_dict({**latest.to_dict(), **changes})
        validate_tasks([updated if task.id == task_id else task for task in tasks])
        actual_changes = {
            field: getattr(updated, field)
            for field in changes
            if getattr(updated, field) != getattr(latest, field)
        }
        if not actual_changes:
            return latest
        updated.updated_at = _utc_now()
        actual_changes["updated_at"] = updated.updated_at
        row_number = positions[task_id]
        field_columns = {TASK_HEADERS[header]: index for index, header in enumerate(headers)}
        data = [
            {
                "range": _a1(TASK_SHEET, f"{_column(field_columns[field])}{row_number}"),
                "values": [[value]],
            }
            for field, value in actual_changes.items()
        ]
        self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()
        try:
            verified = next((task for task in self.get_tasks() if task.id == task_id), None)
        except Exception as exc:
            raise WriteUncertainError(
                "수정 요청은 전송됐지만 재조회에 실패해 반영 상태를 확인하지 못했습니다. "
                "기존 요청 ID로 재시도하면 최신 값을 확인하고 기록·공지를 복구합니다."
            ) from exc
        if verified is None or verified.to_dict() != updated.to_dict():
            raise WriteUncertainError(
                "수정 요청은 전송됐지만 다시 읽은 시트가 예상 결과와 다릅니다. "
                "동시 편집 여부와 시트 값을 확인해 주세요. 자동 재수정이나 되돌리기는 하지 않았습니다."
            )
        return verified

    def _append(self, tab: str, record: dict[str, object]) -> None:
        self._require_writes()
        event_id = record["기록ID"]
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("기록ID는 비어 있지 않은 문자열이어야 합니다.")
        headers, rows, bound = self._read_table(tab)
        id_column = headers.index("기록ID")
        if any(len(row) > id_column and str(row[id_column]) == event_id for row in rows):
            return
        last_used_row = 1
        for row_number, row in enumerate(rows, start=2):
            if any(value not in (None, "") for value in row):
                last_used_row = row_number
        next_row = last_used_row + 1
        if next_row > bound:
            raise ValueError(
                f"'{tab}' 탭의 기록 공간이 찼습니다({bound}행). 기존 기록을 보관하거나 "
                f"최대 {SCHEMAS[tab]['max_rows']}행 안에서 행을 추가한 뒤 다시 실행해 주세요."
            )
        values = [record[header] for header in headers]
        # Explicit end row avoids values.append's table inference when rows are blank.
        target = _a1(tab, f"A{next_row}:{_column(len(headers) - 1)}{next_row}")
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=target,
            valueInputOption="RAW",
            body={"values": [values]},
        ).execute()
        try:
            readback = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=target, valueRenderOption="UNFORMATTED_VALUE"
            ).execute().get("values", [])
            actual = readback[0] if readback else []
            actual += [""] * (len(values) - len(actual))
        except Exception as exc:
            raise WriteUncertainError(
                f"'{tab}' 기록 요청은 전송됐지만 재조회에 실패했습니다. "
                f"같은 기록ID '{event_id}'로 재시도하면 중복을 확인합니다."
            ) from exc
        if actual != values:
            raise WriteUncertainError(
                f"'{tab}' 기록 요청은 전송됐지만 재조회 값이 다릅니다. 기록ID '{event_id}'를 확인해 주세요."
            )

    def append_result(self, event_id: str, task: Task, report: dict) -> None:
        self._require_writes()
        self._append(RESULT_SHEET, {
            "기록ID": event_id,
            "업무ID": task.id,
            "조회일": report.get("checked_at") or _utc_now(),
            "영역": task.category,
            "지역": task.region,
            "요약": report.get("summary", ""),
            "출처JSON": json.dumps(report.get("sources", []), ensure_ascii=False),
        })

    def append_change(self, event_id: str, task_id: str, actor: str, changes: dict) -> None:
        self._require_writes()
        self._append(CHANGE_SHEET, {
            "기록ID": event_id,
            "시각": _utc_now(),
            "업무ID": task_id,
            "요청자": actor,
            "변경JSON": json.dumps(changes, ensure_ascii=False),
        })

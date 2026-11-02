from __future__ import annotations

import shlex
from datetime import datetime

from .models import EDITABLE_FIELDS, TASK_HEADERS, Task, parse_bool, validate_tasks


HELP = """결혼 준비 도우미
/status — 준비 현황
/schedule — 앞으로의 일정
/research W001 — 해당 업무 업체 조사
/edit W001 상태=계약완료 업체="예시 스튜디오"
/edit W002 마감일=2027-04 담당=공동
/edit W001 조사여부=아니오
/edit W002 예약일시=2027-04-10T14:00+09:00

수정 가능한 열: 영역, 할일, 상태, 마감일, 담당, 지역, 예산, 조사여부, 업체, 예약일시, 선행업무, 메모
빈 값으로 지우기: 메모=""
월 단위 마감은 월말로 계산합니다. 예약/계약과 촬영 실행은 별도 업무로 관리합니다.
그룹에서는 /edit@봇아이디처럼 봇을 지정할 수 있습니다."""


class Commands:
    def __init__(self, engine):
        self.engine = engine

    def handle(self, update_id: str, text: str, actor: str, now: datetime | None = None) -> bool:
        """Return False for ordinary conversation. Durable intents recover interrupted edits."""
        now = now or self.engine.now()
        state = self.engine.state
        command_key = "command:" + str(update_id)
        if state.get(command_key):
            return True
        if not text.startswith("/"):
            return False
        try:
            tokens = shlex.split(text)
            if not tokens:
                return False
            command = tokens[0].split("@", 1)[0].lower()
            aliases = {"/도움말": "/help", "/현황": "/status", "/일정": "/schedule",
                       "/조사": "/research", "/수정": "/edit", "/start": "/help"}
            command = aliases.get(command, command)
            if command == "/edit":
                self._edit(update_id, tokens[1:], actor)
                state.put(command_key, True)
                return True
            if command == "/help":
                reply = HELP
            elif command in {"/status", "/schedule"}:
                tasks = self.engine.repository.get_tasks()
                if command == "/schedule":
                    tasks = sorted((task for task in tasks if task.active),
                                   key=lambda task: str(self.engine.due_date(task) or "9999"))
                rows = [f"{task.id} · {task.title} · {task.status}\n  목표: {self.engine.due_date(task) or '미입력'} / 담당: {task.owner} / 조사: {'켜짐' if task.needs_research else '꺼짐'}" for task in tasks]
                reply = "[준비 현황]" + ("\n" + "\n".join(rows) if rows else "\n등록된 업무가 없습니다.")
            elif command == "/research":
                if len(tokens) != 2:
                    raise ValueError("사용법: /research W001")
                reply = self.engine.research_task(self.engine.task(tokens[1]), now, force=True)
            else:
                reply = "지원하는 명령은 /help에서 확인해 주세요."
            state.enqueue(command_key, {"kind": "reply", "text": reply})
            state.put(command_key, True)
        except ValueError as exc:
            state.enqueue(command_key, {"kind": "reply", "text": f"요청을 반영하지 못했습니다. {exc}"})
            state.put(command_key, True)
        return True

    def _edit(self, update_id: str, tokens: list[str], actor: str):
        if len(tokens) < 2:
            raise ValueError('사용법: /edit W001 상태=계약완료 업체="예시 스튜디오"')
        state, repo = self.engine.state, self.engine.repository
        intent_key = "edit-intent:" + str(update_id)
        intent = state.get(intent_key)
        if not intent:
            task = self.engine.task(tokens[0])
            changes = {}
            for token in tokens[1:]:
                if "=" not in token:
                    raise ValueError('각 항목을 열이름=값으로 입력하고, 공백이 있으면 큰따옴표로 묶어 주세요.')
                name, value = token.split("=", 1)
                field = TASK_HEADERS.get(name, name)
                if field not in EDITABLE_FIELDS:
                    raise ValueError(f"수정할 수 없는 열: {name}")
                if field in changes:
                    raise ValueError(f"같은 열을 두 번 지정했습니다: {name}")
                if len(value) > 5000:
                    raise ValueError("입력값은 열마다 5,000자 이내로 입력해 주세요.")
                changes[field] = parse_bool(value) if field == "research_enabled" else value
            new = Task.from_dict(task.to_dict() | changes)
            validate_tasks([new if item.id == task.id else item for item in repo.get_tasks()])
            diff = {field: {"before": getattr(task, field), "after": value}
                    for field, value in changes.items() if getattr(task, field) != value}
            if not diff:
                state.enqueue("command:" + str(update_id), {"kind": "reply", "text": "이미 같은 값이 기록되어 있습니다. 변경하지 않았습니다."})
                return
            intent = {"task_id": task.id, "expected": task.to_dict(), "changes": diff, "actor": actor}
            state.put(intent_key, intent)
        task = self.engine.task(intent["task_id"])
        desired = {field: change["after"] for field, change in intent["changes"].items()}
        if not all(getattr(task, field) == value for field, value in desired.items()):
            repo.update_task(task.id, desired, expected=Task.from_dict(intent["expected"]))
        # If a process died after saving the Sheet, matching desired values recover the audit/message.
        labels = {value: key for key, value in TASK_HEADERS.items()}
        def display(value):
            if isinstance(value, bool):
                return "예" if value else "아니오"
            return value if value != "" else "(비어 있음)"
        changes_text = "\n".join(f"• {labels[field]}: {display(change['before'])} → {display(change['after'])}"
                                 for field, change in intent["changes"].items())
        target = "로컬 예제" if self.engine.settings.mode == "demo" else "Google Sheets"
        text = f"[{target} 수정 완료] {task.id} · {task.title}\n요청자: {intent['actor']}\n{changes_text}"
        state.enqueue("change:" + str(update_id), {"kind": "change", "task_id": task.id,
            "actor": intent["actor"], "changes": intent["changes"], "text": text})

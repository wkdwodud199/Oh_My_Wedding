from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from .messaging import split_message
from .models import Task
from .research import ResearchError


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def reminder_bucket(days: int, thresholds: tuple[int, ...]) -> str | None:
    if days < 0:
        return f"overdue-{(-days - 1) // 7}"
    crossed = [threshold for threshold in thresholds if days <= threshold]
    return f"before-{min(crossed)}" if crossed else None


class Engine:
    def __init__(self, settings, repository, state, researcher, messenger):
        self.settings, self.repository, self.state = settings, repository, state
        self.researcher, self.messenger = researcher, messenger

    def now(self):
        return datetime.now(self.settings.tz)

    def in_notification_window(self, now: datetime) -> bool:
        return self.settings.digest_hour <= now.hour < self.settings.quiet_end_hour

    def task(self, task_id: str) -> Task:
        task = next((item for item in self.repository.get_tasks() if item.id == task_id), None)
        if not task:
            raise ValueError(f"업무ID를 찾을 수 없습니다: {task_id}. /status로 확인해 주세요.")
        return task

    def due_date(self, task: Task):
        if task.due:
            return task.due
        if task.appointment:
            return datetime.fromisoformat(task.appointment).astimezone(self.settings.tz).date()
        return None

    def reminder_text(self, task: Task, tasks: list[Task], now: datetime) -> str:
        due = self.due_date(task)
        days = (due - now.date()).days
        timing = f"{days}일 남았습니다" if days > 0 else ("오늘이 마감입니다" if days == 0 else f"{abs(days)}일 지났습니다")
        text = f"[준비 일정] {task.id} · {task.title}\n목표일 {due} · {timing}. 준비가 되셨을까요?\n현재 {task.status} / 담당 {task.owner}"
        if len(task.deadline) == 7:
            text += "\n월 단위 목표를 해당 월의 마지막 날로 계산했습니다."
        parent = next((item for item in tasks if item.id == task.depends_on), None)
        if parent and parent.active:
            text += f"\n먼저 필요한 일: {parent.id} {parent.title} ({parent.status})"
        return text + f"\n완료했다면 /edit {task.id} 상태=완료\n작성 기준: {now.date()}"

    def schedule_reminders(self, tasks: list[Task], now: datetime):
        for task in tasks:
            due = self.due_date(task)
            if not task.active or due is None:
                continue
            days = (due - now.date()).days
            bucket = reminder_bucket(days, self.settings.reminder_days)
            if bucket is None:
                continue
            event_id = f"reminder:{task.id}:{due}:{bucket}"
            if self.state.has_event(event_id):
                continue
            text = self.reminder_text(task, tasks, now)
            self.state.enqueue(event_id, {"kind": "reminder", "task_id": task.id,
                                          "due": str(due), "bucket": bucket, "text": text})

    def research_key(self, task: Task):
        return "research-state:" + digest([task.id, task.category, task.region, task.budget])

    def research_task(self, task: Task, now: datetime, force: bool = False) -> str:
        if not task.needs_research:
            return f"{task.id}: 조사여부가 켜진 미정·조사중·상담중 업무만 조사합니다."
        if not task.region.strip():
            return f"{task.id}: 조사 지역을 먼저 입력해 주세요. 예: /edit {task.id} 지역=서울"
        key = self.research_key(task)
        previous = self.state.get(key, {})
        checked = previous.get("checked_at")
        if checked and not force:
            if now - datetime.fromisoformat(checked) < timedelta(days=self.settings.research_interval_days):
                return "조사 주기가 아직 지나지 않았습니다."
        if not self.researcher:
            raise ValueError("업체 조사에 TAVILY_API_KEY가 필요합니다.")
        report = self.researcher.research(task.category, task.region, task.budget)
        changed = report.signature != previous.get("signature")
        revision = previous.get("revision", 0) + int(changed)
        if changed:
            event_id = f"research:{task.id}:{revision}:{digest([key, report.signature])}"
            data = report.as_dict()
            data["checked_at"] = now.isoformat()
            self.state.enqueue(event_id, {"kind": "research", "task_id": task.id,
                "task": task.to_dict(), "report": data,
                "text": f"[업체 조사] {task.id} · {task.title}\n" + report.text(), "manual": force})
        self.state.put(key, {"checked_at": now.isoformat(), "signature": report.signature, "revision": revision})
        return "새 조사 결과를 기록하고 공유합니다." if changed else "지난 조사와 출처 내용이 같아 중복 공지는 생략합니다."

    def run_once(self, now: datetime | None = None):
        now = (now or self.now()).astimezone(self.settings.tz)
        if self.in_notification_window(now):
            tasks = self.repository.get_tasks()
            self.schedule_reminders(tasks, now)
            # Oldest checks first; a broken search cannot starve all other tasks.
            candidates = sorted((task for task in tasks if task.needs_research),
                key=lambda task: self.state.get(self.research_key(task), {}).get("checked_at", ""))
            searches = 0
            for task in candidates:
                last = self.state.get(self.research_key(task), {}).get("checked_at")
                if last and now - datetime.fromisoformat(last) < timedelta(days=self.settings.research_interval_days):
                    continue
                failure_at = self.state.get("research-failure:" + task.id)
                if failure_at and now - datetime.fromisoformat(failure_at) < timedelta(hours=1):
                    continue
                if task.region.strip() and searches >= self.settings.max_research_per_run:
                    break
                searches += int(bool(task.region.strip()))
                try:
                    message = self.research_task(task, now)
                    if not task.region.strip():
                        self.state.enqueue(f"missing-region:{task.id}:{now.date()}",
                            {"kind": "notice", "text": message})
                        self.state.put("research-failure:" + task.id, now.isoformat())
                except Exception as exc:
                    self.state.put("research-failure:" + task.id, now.isoformat())
                    detail = str(exc) if isinstance(exc, (ResearchError, ValueError)) else type(exc).__name__
                    self.state.enqueue(f"research-error:{task.id}:{now.date()}", {"kind": "notice",
                        "text": f"[조사 실패] {task.id} {task.title} · {detail}. 설정/네트워크를 확인해 주세요. 다음 실행에서 재시도합니다."})
        return self.flush(now)

    def flush(self, now: datetime | None = None) -> list[str]:
        now = (now or self.now()).astimezone(self.settings.tz)
        errors = []
        for event in self.state.pending():
            payload = event["payload"]
            if payload["kind"] in {"reminder", "research", "notice"} and not payload.get("manual"):
                if not self.in_notification_window(now):
                    continue
            try:
                if payload["kind"] in {"reminder", "research"}:
                    latest = next((task for task in self.repository.get_tasks() if task.id == payload["task_id"]), None)
                    if latest is None:
                        self.state.progress(event["id"], done=1)
                        continue
                    stale = not latest.active
                    if payload["kind"] == "research":
                        saved = Task.from_dict(payload["task"])
                        stale |= not latest.needs_research or self.research_key(saved) != self.research_key(latest)
                    else:
                        due = self.due_date(latest)
                        stale |= str(due) != payload["due"]
                        if due:
                            stale |= reminder_bucket((due - now.date()).days, self.settings.reminder_days) != payload["bucket"]
                    if stale:
                        self.state.progress(event["id"], done=1)
                        continue
                    if payload["kind"] == "reminder" and event["sent_parts"] == 0:
                        payload["text"] = self.reminder_text(latest, self.repository.get_tasks(), now)
                        self.state.replace_payload(event["id"], payload)
                if not event["sheet_done"]:
                    if payload["kind"] == "research":
                        self.repository.append_result(event["id"], Task.from_dict(payload["task"]), payload["report"])
                    elif payload["kind"] == "change":
                        self.repository.append_change(event["id"], payload["task_id"], payload["actor"], payload["changes"])
                    self.state.progress(event["id"], sheet_done=1)
                parts = split_message(payload["text"])
                for index in range(event["sent_parts"], len(parts)):
                    self.messenger.send(parts[index])
                    self.state.progress(event["id"], sent_parts=index + 1)
                self.state.progress(event["id"], done=1, last_error="")
            except Exception as exc:
                error = f"{event['id']}: {type(exc).__name__}"
                self.state.progress(event["id"], last_error=error)
                errors.append(error)
        return errors

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class State:
    """Single-worker durable state. Queue external writes before delivering messages."""

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                sheet_done INTEGER NOT NULL DEFAULT 0,
                sent_parts INTEGER NOT NULL DEFAULT 0,
                done INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
        """)
        self.db.commit()

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def bind(self, context: dict):
        current = self.get("instance-context")
        if current is None:
            if self.db.execute("SELECT COUNT(*) FROM kv").fetchone()[0] or self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]:
                raise ValueError("이 상태 파일에는 대상 식별정보 없는 기존 기록이 있습니다. 새 STATE_PATH를 지정해 주세요.")
            self.put("instance-context", context)
        elif current != context:
            raise ValueError("이 상태 파일은 다른 모드·시트·대화방에 속합니다. demo/live별 다른 STATE_PATH를 사용해 주세요.")

    def put(self, key: str, value):
        self.db.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def enqueue(self, event_id: str, payload: dict):
        self.db.execute("INSERT OR IGNORE INTO outbox(id,payload) VALUES (?,?)",
                        (event_id, json.dumps(payload, ensure_ascii=False)))
        self.db.commit()

    def pending(self):
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in
                self.db.execute("SELECT * FROM outbox WHERE done=0 ORDER BY rowid")]

    def has_event(self, event_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM outbox WHERE id=?", (event_id,)).fetchone() is not None

    def replace_payload(self, event_id: str, payload: dict):
        self.db.execute("UPDATE outbox SET payload=? WHERE id=?",
                        (json.dumps(payload, ensure_ascii=False), event_id))
        self.db.commit()

    def progress(self, event_id: str, **changes):
        if not changes.keys() <= {"sheet_done", "sent_parts", "done", "last_error"}:
            raise ValueError("Unknown outbox field")
        columns = ",".join(f"{key}=?" for key in changes)
        self.db.execute(f"UPDATE outbox SET {columns} WHERE id=?", (*changes.values(), event_id))
        self.db.commit()

    def close(self):
        self.db.close()


class JsonRepository:
    """Local demo source. Never accesses Google Sheets."""

    def __init__(self, path: str):
        self.path = Path(path)

    def get_tasks(self):
        from .models import Task, validate_tasks
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return validate_tasks([Task.from_dict(task) for task in data])

    def update_task(self, task_id: str, changes: dict, expected=None):
        from .models import EDITABLE_FIELDS, Task, validate_tasks
        if not changes.keys() <= EDITABLE_FIELDS:
            raise ValueError("수정할 수 없는 열입니다.")
        tasks = self.get_tasks()
        old = next((task for task in tasks if task.id == task_id), None)
        if old is None:
            raise ValueError(f"업무ID를 찾을 수 없습니다: {task_id}")
        if expected and old.to_dict() != expected.to_dict():
            raise ValueError("업무가 그 사이 변경되었습니다. 최신 현황을 보고 다시 요청해 주세요.")
        new = Task.from_dict(old.to_dict() | changes | {"updated_at": datetime.now(timezone.utc).isoformat()})
        tasks = validate_tasks([new if task.id == task_id else task for task in tasks])
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps([task.to_dict() for task in tasks], ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
        return new

    def _append(self, kind: str, event_id: str, record: dict):
        path = self.path.with_name(f"{kind}.jsonl")
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if json.loads(line)["event_id"] == event_id:
                    return
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"event_id": event_id, **record}, ensure_ascii=False) + "\n")

    def append_result(self, event_id: str, task, report: dict):
        self._append("research", event_id, {"task_id": task.id, **report})

    def append_change(self, event_id: str, task_id: str, actor: str, changes: dict):
        self._append("changes", event_id, {"task_id": task_id, "actor": actor, "changes": changes})

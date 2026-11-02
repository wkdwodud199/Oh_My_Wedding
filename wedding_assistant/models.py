from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime


TASK_HEADERS = {
    "업무ID": "id", "영역": "category", "할일": "title", "상태": "status",
    "마감일": "deadline", "담당": "owner", "지역": "region", "예산": "budget",
    "조사여부": "research_enabled", "업체": "vendor", "예약일시": "appointment",
    "선행업무": "depends_on", "메모": "notes", "수정시각": "updated_at",
}
STATUSES = {"미정", "조사중", "상담중", "예약완료", "계약완료", "완료", "보류", "취소"}
CLOSED_STATUSES = {"예약완료", "계약완료", "완료", "취소"}
RESEARCH_STATUSES = {"미정", "조사중", "상담중"}
EDITABLE_FIELDS = set(TASK_HEADERS.values()) - {"id", "updated_at"}


def parse_deadline(value: str) -> date | None:
    """A month-only target means the last day of that month, never an invented year."""
    if not value:
        return None
    if len(value) == 7:
        first = date.fromisoformat(value + "-01")
        return first.replace(day=calendar.monthrange(first.year, first.month)[1])
    if len(value) != 10:
        raise ValueError("마감일은 YYYY-MM-DD 또는 YYYY-MM 형식으로 입력해 주세요.")
    return date.fromisoformat(value)


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    value = str(value).strip().lower()
    if value in {"true", "y", "yes", "1", "예", "켜기"}:
        return True
    if value in {"false", "n", "no", "0", "아니오", "끄기", ""}:
        return False
    raise ValueError("조사여부는 예/아니오 또는 TRUE/FALSE로 입력해 주세요.")


@dataclass
class Task:
    id: str
    category: str
    title: str
    status: str = "미정"
    deadline: str = ""
    owner: str = "공동"
    region: str = ""
    budget: str = ""
    research_enabled: bool = False
    vendor: str = ""
    appointment: str = ""
    depends_on: str = ""
    notes: str = ""
    updated_at: str = ""

    def __post_init__(self):
        self.research_enabled = parse_bool(self.research_enabled)
        if not self.id.strip() or not self.title.strip() or not self.category.strip():
            raise ValueError("업무ID, 영역, 할일은 필수입니다.")
        if self.status not in STATUSES:
            raise ValueError(f"알 수 없는 상태: {self.status}")
        parse_deadline(self.deadline)
        if self.appointment:
            stamp = datetime.fromisoformat(self.appointment)
            if stamp.tzinfo is None:
                raise ValueError("예약일시는 시간대를 포함해 주세요. 예: 2027-04-10T14:00+09:00")

    @property
    def due(self) -> date | None:
        return parse_deadline(self.deadline)

    @property
    def active(self) -> bool:
        return self.status not in CLOSED_STATUSES | {"보류"}

    @property
    def needs_research(self) -> bool:
        return self.research_enabled and self.status in RESEARCH_STATUSES

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in allowed})


def validate_tasks(tasks: list[Task]) -> list[Task]:
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("중복 업무ID가 있습니다. 업무마다 고유한 ID가 필요합니다.")
    by_id = {task.id: task for task in tasks}
    for task in tasks:
        seen = {task.id}
        parent = task.depends_on
        while parent:
            if parent not in by_id:
                raise ValueError(f"{task.id}: 존재하지 않는 선행업무 {parent}")
            if parent in seen:
                raise ValueError(f"{task.id}: 선행업무가 순환합니다.")
            seen.add(parent)
            parent = by_id[parent].depends_on
    return tasks

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass
class Settings:
    mode: str = "demo"
    timezone: str = "Asia/Seoul"
    state_path: str = "data/state.sqlite3"
    local_tasks_path: str = "data/tasks.json"
    spreadsheet_id: str = ""
    google_credentials_file: str = ""
    sheets_write_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    tavily_api_key: str = ""
    ai_backend: str = "codex_oauth"
    codex_command: str = "codex"
    codex_model: str = ""
    codex_timeout_seconds: int = 180
    research_interval_days: int = 7
    max_research_per_run: int = 3
    digest_hour: int = 20
    quiet_end_hour: int = 21
    reminder_days: tuple[int, ...] = (30, 14, 7, 3, 1, 0)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        result = cls(
            mode=os.getenv("WEDDING_MODE", "demo"),
            timezone=os.getenv("TIMEZONE", "Asia/Seoul"),
            state_path=os.getenv("STATE_PATH", f"data/{os.getenv('WEDDING_MODE', 'demo')}-state.sqlite3"),
            local_tasks_path=os.getenv("LOCAL_TASKS_PATH", "data/tasks.json"),
            spreadsheet_id=os.getenv("SPREADSHEET_ID", ""),
            google_credentials_file=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            sheets_write_enabled=os.getenv("SHEETS_WRITE_ENABLED", "false").lower() == "true",
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            ai_backend=os.getenv("AI_BACKEND", "codex_oauth"),
            codex_command=os.getenv("CODEX_COMMAND", "codex"),
            codex_model=os.getenv("CODEX_MODEL", ""),
            codex_timeout_seconds=int(os.getenv("CODEX_TIMEOUT_SECONDS", "180")),
            research_interval_days=int(os.getenv("RESEARCH_INTERVAL_DAYS", "7")),
            max_research_per_run=int(os.getenv("MAX_RESEARCH_PER_RUN", "3")),
            digest_hour=int(os.getenv("DIGEST_HOUR", "20")),
            quiet_end_hour=int(os.getenv("QUIET_END_HOUR", "21")),
        )
        if result.mode not in {"demo", "live"}:
            raise ValueError("WEDDING_MODE는 demo 또는 live여야 합니다.")
        if result.ai_backend not in {"codex_oauth", "none"}:
            raise ValueError("AI_BACKEND는 codex_oauth 또는 none입니다. API 키 기반 AI 인증은 지원하지 않습니다.")
        if result.codex_timeout_seconds < 1:
            raise ValueError("CODEX_TIMEOUT_SECONDS는 1 이상이어야 합니다.")
        if not 0 <= result.digest_hour < result.quiet_end_hour <= 24:
            raise ValueError("DIGEST_HOUR < QUIET_END_HOUR이고 0~24 범위여야 합니다.")
        if result.research_interval_days < 1 or result.max_research_per_run < 1:
            raise ValueError("조사 간격과 실행당 조사 수는 1 이상이어야 합니다.")
        result.tz
        Path(result.state_path).parent.mkdir(parents=True, exist_ok=True)
        return result

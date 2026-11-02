from __future__ import annotations

import argparse
import json
import shutil
import sys
from importlib.resources import files
from datetime import datetime
from pathlib import Path

from .commands import Commands
from .config import Settings
from .engine import Engine
from .messaging import ConsoleMessenger, TelegramMessenger
from .research import DemoResearchProvider, TavilyResearchProvider
from .runtime import serve, single_worker
from .storage import JsonRepository, State


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def init_local(path: str):
    target = Path(path)
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(files("wedding_assistant").joinpath("data/tasks.json").read_text(encoding="utf-8"), encoding="utf-8")


def build_engine(settings: Settings, require_writes: bool = True):
    state = State(settings.state_path)
    context = {"mode": settings.mode}
    if settings.mode == "demo":
        context["tasks_path"] = str(Path(settings.local_tasks_path).resolve())
    else:
        context.update(spreadsheet_id=settings.spreadsheet_id, chat_id=settings.telegram_chat_id)
    try:
        state.bind(context)
    except Exception:
        state.close()
        raise
    if settings.mode == "demo":
        init_local(settings.local_tasks_path)
        repo = JsonRepository(settings.local_tasks_path)
        messenger = ConsoleMessenger()
        researcher = DemoResearchProvider()
    else:
        from .sheets import GoogleSheetsRepository
        if require_writes and not settings.sheets_write_enabled:
            raise ValueError("아직 시트 쓰기가 꺼져 있습니다. 실제 연결 준비 후 SHEETS_WRITE_ENABLED=true로 전환해 주세요. 원본은 변경되지 않았습니다.")
        repo = GoogleSheetsRepository(settings.spreadsheet_id, settings.google_credentials_file,
                                      allow_writes=settings.sheets_write_enabled)
        messenger = TelegramMessenger(settings.telegram_token, settings.telegram_chat_id)
        organizer = None
        if settings.ai_backend == "codex_oauth":
            from .codex_oauth import CodexOAuthClient
            organizer = CodexOAuthClient(settings.codex_command, settings.codex_model, settings.codex_timeout_seconds)
        researcher = TavilyResearchProvider(settings.tavily_api_key, organizer=organizer) if settings.tavily_api_key else None
    return Engine(settings, repo, state, researcher, messenger)


def run_demo(output: str | None):
    target = Path(output) if output else Path("artifacts") / ("demo-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    if target.exists() and any(target.iterdir()):
        raise ValueError("데모 출력 폴더가 비어 있지 않습니다. 새 폴더를 지정해 주세요.")
    target.mkdir(parents=True, exist_ok=True)
    settings = Settings(state_path=str(target / "state.sqlite3"), local_tasks_path=str(target / "tasks.json"))
    engine = build_engine(settings)
    now = datetime(2026, 11, 1, 20, tzinfo=settings.tz)
    first_errors = engine.run_once(now)
    first_count = len(engine.messenger.messages)
    second_errors = engine.run_once(now)
    repeated = len(engine.messenger.messages) - first_count
    Commands(engine).handle("demo-edit-1", '/edit W001 상태=계약완료 업체="가상 스튜디오 A"', "데모 사용자", now)
    edit_errors = engine.flush(now)
    Commands(engine).handle("demo-edit-1", '/edit W001 상태=계약완료 업체="가상 스튜디오 A"', "데모 사용자", now)
    engine.flush(now)
    tasks = engine.repository.get_tasks()
    checks = {
        "실제 외부 호출": False,
        "같은 시각 재실행 추가 공지 수": repeated,
        "수정된 W001 상태": next(task.status for task in tasks if task.id == "W001"),
        "처음부터 계약완료인 W003 조사·일정 공지": any("W003" in text for text in engine.messenger.messages),
        "처리 오류": first_errors + second_errors + edit_errors,
    }
    report = "# 로컬 가상 데이터 실행 결과\n\n실제 결혼 계획·업체 추천·발송 기록이 아닙니다. Google Sheets 변경 및 네트워크 호출 없음.\n\n"
    report += "```json\n" + json.dumps(checks, ensure_ascii=False, indent=2) + "\n```\n\n"
    report += "\n\n---\n\n".join(engine.messenger.messages)
    (target / "transcript.md").write_text(report, encoding="utf-8")
    engine.state.close()
    print(f"\n검증 결과: {target.resolve() / 'transcript.md'}")
    print(json.dumps(checks, ensure_ascii=False))
    if checks["처리 오류"] or repeated or checks["처음부터 계약완료인 W003 조사·일정 공지"]:
        raise RuntimeError("데모 검증 실패")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Oh My Wedding 결혼 준비 도우미")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="외부 연결 없는 전체 흐름 검증")
    demo.add_argument("--output")
    sub.add_parser("init-local", help="로컬 가상 예제 만들기 (기존 파일 보존)")
    tick = sub.add_parser("tick", help="현재 시각 기준 주기 작업 한 번 실행")
    tick.add_argument("--at", help="demo 전용 ISO 시각")
    chat = sub.add_parser("chat", help="명령 한 번 실행 (demo는 로컬, live는 실제 반영/공지)")
    chat.add_argument("text")
    sub.add_parser("serve", help="Telegram 수신 + 주기 작업 상시 실행")
    doctor = sub.add_parser("doctor", help="설정 검사; 기본값은 외부 호출 없음")
    doctor.add_argument("--check-connections", action="store_true", help="Google Sheets/Telegram 읽기 연결 확인")
    sub.add_parser("telegram-info", help="봇이 받은 그룹 chat_id만 조회, 발송 없음")
    oauth = sub.add_parser("oauth-check", help="Codex ChatGPT 로그인 확인 (토큰 내용 읽기/출력 없음)")
    oauth.add_argument("--infer", action="store_true", help="작은 JSON 응답을 실제 ChatGPT OAuth로 요청")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            run_demo(args.output)
            return 0
        settings = Settings.from_env()
        if args.command == "oauth-check":
            from .codex_oauth import CodexOAuthClient
            client = CodexOAuthClient(settings.codex_command, settings.codex_model, settings.codex_timeout_seconds)
            client.check_login()
            print("Codex ChatGPT OAuth 로그인 확인 완료")
            if args.infer:
                schema = {"type": "object", "properties": {"status": {"type": "string", "enum": ["ok"]}},
                          "required": ["status"], "additionalProperties": False}
                result = client.complete_json('Return exactly the JSON object {"status":"ok"}. Do not use any tools.', schema)
                if result != {"status": "ok"}:
                    raise ValueError("OAuth 응답이 확인 형식과 다릅니다.")
                print("ChatGPT OAuth 실제 JSON 응답 확인: ok (시트/Telegram 호출 없음)")
            return 0
        if args.command == "init-local":
            init_local(settings.local_tasks_path)
            print(f"로컬 예제: {Path(settings.local_tasks_path).resolve()}")
            return 0
        if args.command == "telegram-info":
            messenger = TelegramMessenger(settings.telegram_token, settings.telegram_chat_id or "0")
            bot = messenger.check()
            print(f"봇: @{bot['username']}")
            updates = messenger.poll(0, timeout=0)
            chats = {str(item.get('message', {}).get('chat', {}).get('id')):
                     item.get('message', {}).get('chat', {}).get('type') for item in updates if item.get('message')}
            print(json.dumps(chats, ensure_ascii=False) if chats else "그룹에서 /help@봇아이디를 보낸 뒤 다시 실행하세요.")
            return 0
        if args.command == "doctor":
            checks = {"mode": settings.mode, "시트 쓰기": settings.sheets_write_enabled,
                "Google 파일 ID": bool(settings.spreadsheet_id), "Google 자격증명 경로": bool(settings.google_credentials_file),
                "Telegram 토큰": bool(settings.telegram_token), "Telegram 대화방": bool(settings.telegram_chat_id),
                "Tavily 검색": bool(settings.tavily_api_key), "AI 인증 방식": settings.ai_backend}
            print(json.dumps(checks, ensure_ascii=False, indent=2))
            if args.check_connections:
                if settings.mode != "live":
                    print("demo 모드에서는 외부 연결을 확인하지 않습니다.")
                else:
                    engine = build_engine(settings, require_writes=False)
                    print(f"준비업무 읽기 성공: {len(engine.repository.get_tasks())}개")
                    print(f"Telegram 읽기 성공: @{engine.messenger.check()['username']}")
                    engine.state.close()
            return 0
        if args.command == "serve" and settings.mode != "live":
            raise ValueError("상시 Telegram 연결은 live 모드에서 실행합니다. 로컬 검증은 demo 또는 chat을 사용하세요.")
        if args.command == "tick" and args.at and settings.mode != "demo":
            raise ValueError("--at 시각 변경은 demo에서만 사용할 수 있습니다.")
        with single_worker(settings.state_path):
            engine = build_engine(settings)
            try:
                if args.command == "serve":
                    serve(engine)
                elif args.command == "tick":
                    now = datetime.fromisoformat(args.at) if args.at else None
                    if now is not None and now.tzinfo is None:
                        raise ValueError("--at에는 +09:00 같은 시간대를 포함해 주세요.")
                    errors = engine.run_once(now)
                    if errors:
                        print("\n".join(errors))
                        return 1
                elif args.command == "chat":
                    Commands(engine).handle("cli-" + datetime.now().isoformat(), args.text, "로컬 실행자")
                    errors = engine.flush()
                    if errors:
                        print("\n".join(errors))
                        return 1
            finally:
                engine.state.close()
        return 0
    except (ValueError, PermissionError) as exc:
        print(f"설정/입력 확인: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"연동 확인 필요: {type(exc).__name__} (토큰 보호를 위해 요청 URL은 출력하지 않습니다.)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

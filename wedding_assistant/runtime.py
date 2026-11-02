from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from .commands import Commands
from .research import ResearchError


@contextmanager
def single_worker(state_path: str):
    """A local lock prevents accidentally running two pollers against one state file."""
    path = Path(state_path).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0)
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("같은 상태 파일을 사용하는 도우미가 이미 실행 중입니다.") from None
    try:
        yield
    finally:
        handle.close()


def process_updates(engine, updates: list[dict], bot_username: str):
    commands = Commands(engine)
    for update in updates:
        update_id = update["update_id"]
        message = update.get("message", {})
        text = message.get("text", "")
        expected_chat = engine.settings.telegram_chat_id
        allowed = str(message.get("chat", {}).get("id", "")) == expected_chat
        sender = message.get("from", {})
        allowed &= not sender.get("is_bot", False)
        first = text.split(maxsplit=1)[0] if text else ""
        if first.startswith("/") and "@" in first:
            allowed &= first.split("@", 1)[1].lower() == bot_username.lower()
        if allowed and text:
            # User IDs disambiguate two people with the same display name; no account system needed.
            actor = f"{sender.get('first_name', '사용자')} ({sender.get('id', 'unknown')})"
            commands.handle(str(update_id), text, actor)
        # On a transient command failure an exception stops the batch before advancing the cursor.
        # Outbox delivery is retried independently, so a send failure does not repeat a sheet edit.
        engine.state.put("telegram-offset", update_id + 1)


def serve(engine):
    engine.repository.get_tasks()  # Fail fast on missing schema or credentials, without writing.
    bot = engine.messenger.check()
    username = bot["username"]
    print(f"@{username} 실행 중. 서울 시간 알림 {engine.settings.digest_hour}시. 종료: Ctrl+C")
    next_tick = 0.0
    while True:
        try:
            if time.monotonic() >= next_tick:
                engine.run_once()
                next_tick = time.monotonic() + 60
            updates = engine.messenger.poll(engine.state.get("telegram-offset", 0))
            process_updates(engine, updates, username)
            for error in engine.flush():
                print(f"재시도 대기: {error}")
        except KeyboardInterrupt:
            return
        except Exception as exc:
            # External libraries sometimes include credential-bearing request URLs in errors.
            print(f"작업 재시도 대기: {type(exc).__name__}")
            now = engine.now()
            detail = str(exc) if isinstance(exc, ResearchError) else type(exc).__name__
            engine.state.enqueue(f"runtime-error:{now.date()}", {"kind": "reply", "text":
                f"[도우미 연결 확인 필요] {detail}: 시트·검색·메신저 설정 또는 네트워크를 확인해 주세요. 처리 중인 요청은 저장되어 있으며 재시도합니다."})
            engine.flush()
            time.sleep(5)

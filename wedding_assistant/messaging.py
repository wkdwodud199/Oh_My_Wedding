from __future__ import annotations

import httpx


def split_message(text: str, limit: int = 3000) -> list[str]:
    # 3000 Unicode codepoints stay below Telegram's 4096 character limit for our Korean text.
    # Bound UTF-16 units too, so a report containing emoji cannot accidentally exceed it.
    chunks, current, units = [], [], 0
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if units + size > limit:
            chunks.append("".join(current))
            current, units = [], 0
        current.append(char)
        units += size
    if current:
        chunks.append("".join(current))
    return chunks or ["(내용 없음)"]


class ConsoleMessenger:
    def __init__(self):
        self.messages = []

    def send(self, text: str):
        self.messages.append(text)
        print("\n[로컬 데모 공지 — 실제 발송 아님]\n" + text)


class TelegramMessenger:
    def __init__(self, token: str, chat_id: str, client=None):
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID가 필요합니다.")
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)
        self.client = client or httpx.Client(timeout=40)

    def _call(self, method: str, payload: dict):
        try:
            response = self.client.post(self.base_url + method, json=payload)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram {method} 요청 실패 (code={data.get('error_code', 'unknown')})")
            return data.get("result")
        except (httpx.HTTPError, ValueError) as exc:
            # httpx exception strings contain the bot token in the URL.
            raise RuntimeError(f"Telegram {method} 통신 실패 ({type(exc).__name__})") from None

    def send(self, text: str):
        return self._call("sendMessage", {"chat_id": self.chat_id, "text": text,
                                         "link_preview_options": {"is_disabled": True}})

    def poll(self, offset: int, timeout: int = 20):
        return self._call("getUpdates", {"offset": offset, "timeout": timeout,
                                         "allowed_updates": ["message"]}) or []

    def check(self):
        info = self._call("getWebhookInfo", {})
        if info.get("url"):
            raise ValueError("이 봇에 webhook이 설정되어 있습니다. 기존 용도를 확인하고 해제한 뒤 polling을 실행해 주세요.")
        return self._call("getMe", {})

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from wedding_assistant.commands import Commands
from wedding_assistant.config import Settings
from wedding_assistant.engine import Engine
from wedding_assistant.messaging import TelegramMessenger, split_message
from wedding_assistant.models import Task
from wedding_assistant.runtime import process_updates
from wedding_assistant.storage import JsonRepository, State


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "tasks.json"
        path.write_text(json.dumps([Task("W001", "스튜디오", "계약").to_dict()]), encoding="utf-8")
        self.state = State(":memory:")
        self.engine = Engine(Settings(telegram_chat_id="-1001"), JsonRepository(str(path)), self.state, None, None)

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def update(self, uid=1, chat=-1001, text="/edit W001 상태=완료", is_bot=False):
        return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text,
                                              "from": {"id": 11, "first_name": "예제", "is_bot": is_bot}}}

    def test_other_chat_and_bot_target_and_bot_sender_are_ignored(self):
        updates = [self.update(1, chat=-1002), self.update(2, text="/edit@otherbot W001 상태=완료"),
                   self.update(3, is_bot=True)]
        process_updates(self.engine, updates, "WeddingBot")
        self.assertEqual("미정", self.engine.task("W001").status)
        self.assertEqual(4, self.state.get("telegram-offset"))
        self.assertFalse(self.state.pending())

    def test_own_bot_command_and_replayed_update(self):
        update = self.update(text="/edit@WeddingBot W001 상태=완료")
        process_updates(self.engine, [update], "WeddingBot")
        process_updates(self.engine, [update], "WeddingBot")
        self.assertEqual("완료", self.engine.task("W001").status)
        self.assertEqual(1, len(self.state.pending()))

    def test_transient_failure_does_not_advance_cursor(self):
        with patch.object(Commands, "handle", side_effect=RuntimeError("temporary")):
            with self.assertRaises(RuntimeError):
                process_updates(self.engine, [self.update()], "WeddingBot")
        self.assertIsNone(self.state.get("telegram-offset"))

    def test_state_cannot_mix_demo_and_live_or_different_targets(self):
        self.state.bind({"mode": "demo", "tasks": "a"})
        self.state.bind({"mode": "demo", "tasks": "a"})
        with self.assertRaisesRegex(ValueError, "STATE_PATH"):
            self.state.bind({"mode": "live", "sheet": "real", "chat": "real"})
        with self.assertRaisesRegex(ValueError, "STATE_PATH"):
            self.state.bind({"mode": "demo", "tasks": "b"})

    def test_unbound_old_queue_is_not_adopted(self):
        self.state.enqueue("old", {"kind": "reply", "text": "old demo"})
        with self.assertRaises(ValueError):
            self.state.bind({"mode": "live"})

    def test_telegram_http_error_does_not_expose_token(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401, request=request)))
        messenger = TelegramMessenger("secret-example-token", "-1001", client)
        with self.assertRaises(RuntimeError) as ctx:
            messenger.send("hello")
        self.assertNotIn("secret-example-token", str(ctx.exception))

    def test_poll_parameters_and_webhook_conflict(self):
        requests = []
        def transport(request):
            requests.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
            return httpx.Response(200, json={"ok": True, "result": {"url": "https://example.invalid/webhook"}})
        messenger = TelegramMessenger("example", "-1001", httpx.Client(transport=httpx.MockTransport(transport)))
        messenger.poll(42, timeout=20)
        self.assertEqual({"offset": 42, "timeout": 20, "allowed_updates": ["message"]}, requests[0][1])
        with self.assertRaisesRegex(ValueError, "webhook"):
            messenger.check()

    def test_split_message_keeps_emoji_and_content(self):
        original = ("결혼😀" * 3000)
        parts = split_message(original)
        self.assertEqual(original, "".join(parts))
        self.assertTrue(all(len(part.encode("utf-16-le")) // 2 <= 3000 for part in parts))


if __name__ == "__main__":
    unittest.main()

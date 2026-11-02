from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wedding_assistant.codex_oauth import CodexOAuthClient, CodexOAuthError, _resolve_command


SCHEMA = {
    "type": "object", "properties": {"summary": {"type": "string"}},
    "required": ["summary"], "additionalProperties": False,
}


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.login = "Logged in using ChatGPT"
        self.login_code = 0
        self.exec_code = 0
        self.output = '{"summary":"예시 요약"}'
        self.timeout_at = ""
        self.schemas = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        self.assert_no_shell = kwargs["shell"] is False
        is_login = args[-2:] == ["login", "status"]
        if self.timeout_at == ("login" if is_login else "exec"):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="DO_NOT_LEAK_TOKEN")
        if is_login:
            return SimpleNamespace(returncode=self.login_code, stdout="", stderr=self.login)
        schema_path = Path(args[args.index("--output-schema") + 1])
        self.schemas.append(json.loads(schema_path.read_text(encoding="utf-8")))
        if self.output is not None:
            Path(args[args.index("-o") + 1]).write_text(self.output, encoding="utf-8")
        return SimpleNamespace(returncode=self.exec_code, stdout="DO_NOT_LEAK_TOKEN", stderr="DO_NOT_LEAK_TOKEN")


class CodexOAuthTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.client = CodexOAuthClient(runner=self.runner)
        resolve = patch("wedding_assistant.codex_oauth._resolve_command", return_value=["/fake/codex"])
        resolve.start()
        self.addCleanup(resolve.stop)

    def test_chatgpt_status_and_every_completion_check_login(self):
        self.assertTrue(self.client.check_login())
        for _ in range(2):
            self.assertEqual(self.client.complete_json("요약해 주세요", SCHEMA), {"summary": "예시 요약"})
        self.assertEqual(len(self.runner.calls), 5)
        self.assertEqual(self.runner.calls[1][0][-2:], ["login", "status"])
        self.assertEqual(self.runner.calls[3][0][-2:], ["login", "status"])

    def test_isolated_stdin_schema_and_no_api_fallback(self):
        secrets = {"OPENAI_API_KEY": "DO_NOT_LEAK_TOKEN", "CODEX_API_KEY": "DO_NOT_LEAK_TOKEN",
                   "CODEX_ACCESS_TOKEN": "DO_NOT_LEAK_TOKEN", "OPENAI_BASE_URL": "https://example.invalid"}
        with patch.dict(os.environ, secrets):
            result = self.client.complete_json('자료: "따옴표" & $(명령 아님)', SCHEMA)
        self.assertEqual(result["summary"], "예시 요약")
        args, options = self.runner.calls[-1]
        self.assertFalse(options["shell"])
        self.assertEqual(options["input"], '자료: "따옴표" & $(명령 아님)')
        self.assertEqual(args[-1], "-")
        self.assertNotIn(options["input"], args)
        self.assertEqual(self.runner.schemas, [SCHEMA])
        self.assertFalse(Path(options["cwd"]).exists())
        self.assertEqual(options["timeout"], 180)
        for _, call_options in self.runner.calls:
            self.assertTrue(secrets.keys().isdisjoint(call_options["env"]))
        for flag in ["--ignore-user-config", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check", "--json"]:
            self.assertIn(flag, args)
        for setting in ['forced_login_method="chatgpt"', "features.shell_tool=false", 'web_search="disabled"',
                        "apps._default.enabled=false", "project_doc_max_bytes=0"]:
            self.assertIn(setting, args)

    def test_api_key_auth_rejected_without_inference(self):
        self.runner.login = "Logged in using an API key - DO_NOT_LEAK_TOKEN"
        with self.assertRaisesRegex(ValueError, "API 키 방식") as caught:
            self.client.check_login()
        self.assertNotIn("DO_NOT_LEAK_TOKEN", str(caught.exception))
        with self.assertRaises(CodexOAuthError):
            self.client.complete_json("요약", SCHEMA)
        self.assertEqual(len(self.runner.calls), 2)

    def test_no_login_is_clear_and_does_not_run_model(self):
        self.runner.login = "Not logged in"
        self.runner.login_code = 1
        with self.assertRaisesRegex(ValueError, "codex login"):
            self.client.check_login()
        with self.assertRaises(CodexOAuthError):
            self.client.complete_json("요약", SCHEMA)
        self.assertEqual(len(self.runner.calls), 2)

    def test_exec_failures_do_not_expose_raw_output(self):
        self.runner.exec_code = 1
        with self.assertRaises(CodexOAuthError) as caught:
            self.client.complete_json("요약", SCHEMA)
        self.assertNotIn("DO_NOT_LEAK_TOKEN", str(caught.exception))
        self.assertIn("exit=1", str(caught.exception))

    def test_timeout_has_no_output_or_prompt_in_error(self):
        self.runner.timeout_at = "exec"
        with self.assertRaises(CodexOAuthError) as caught:
            self.client.complete_json("비공개 프롬프트", SCHEMA)
        self.assertIn("180초", str(caught.exception))
        self.assertNotIn("DO_NOT_LEAK_TOKEN", str(caught.exception))
        self.assertNotIn("비공개 프롬프트", str(caught.exception))

    def test_malformed_missing_or_nonobject_json_rejected(self):
        for output in [None, "```json\n{}\n```", "[]", "not JSON"]:
            with self.subTest(output=output):
                self.runner.output = output
                with self.assertRaises(CodexOAuthError):
                    self.client.complete_json("요약", SCHEMA)

    def test_model_and_timeout_preserved(self):
        client = CodexOAuthClient(model="user-requested-model", timeout_seconds=45, runner=self.runner)
        client.complete_json("요약", SCHEMA)
        args, options = self.runner.calls[-1]
        self.assertEqual(args[args.index("--model") + 1], "user-requested-model")
        self.assertEqual(options["timeout"], 45)

    def test_invalid_inputs_do_not_run_process(self):
        for prompt, schema in [("", SCHEMA), ("요약", []), ("요약", {"type": "array"})]:
            with self.assertRaises(CodexOAuthError):
                self.client.complete_json(prompt, schema)
        self.assertEqual(self.runner.calls, [])


class WindowsCommandResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shim = self.root / "codex.cmd"
        self.shim.write_text("npm shim", encoding="utf-8")
        self.package = self.root / "node_modules" / "@openai" / "codex"
        self.script = self.package / "bin" / "codex.js"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("// fake launcher", encoding="utf-8")

    def test_prefers_bundled_executable_over_cmd(self):
        binary = self.package / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
        binary.parent.mkdir(parents=True)
        binary.touch()
        with patch("wedding_assistant.codex_oauth.platform.system", return_value="Windows"), \
             patch("wedding_assistant.codex_oauth.platform.machine", return_value="AMD64"):
            self.assertEqual(_resolve_command(str(self.shim)), [str(binary.resolve())])

    def test_node_and_script_fallback_uses_argv_not_shell(self):
        node = self.root / "node.exe"
        node.touch()
        with patch("wedding_assistant.codex_oauth.platform.system", return_value="Windows"):
            self.assertEqual(_resolve_command(str(self.shim)), [str(node.resolve()), str(self.script.resolve())])

    def test_direct_executable_path_is_kept(self):
        binary = self.root / "path with spaces" / "codex.exe"
        binary.parent.mkdir()
        binary.touch()
        with patch("wedding_assistant.codex_oauth.platform.system", return_value="Windows"):
            self.assertEqual(_resolve_command(str(binary)), [str(binary.resolve())])


if __name__ == "__main__":
    unittest.main()

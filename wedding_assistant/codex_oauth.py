"""Use the official Codex CLI's saved ChatGPT sign-in for JSON inference.

No token files are read or copied here. Authentication and token refresh belong
to Codex. API-key authentication is deliberately not a fallback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


class CodexOAuthError(RuntimeError):
    """ChatGPT-authenticated Codex could not produce a usable JSON response."""


def _resolve_command(command: str) -> list[str]:
    """Resolve npm Windows shims without passing arguments through cmd.exe."""
    candidate = Path(command).expanduser()
    located = str(candidate.resolve()) if candidate.is_file() else shutil.which(command)
    if not located:
        raise ValueError("Codex CLI를 찾을 수 없습니다. 설치 후 CODEX_COMMAND에 실행 파일 경로를 지정해 주세요.")
    path = Path(located).resolve()
    if platform.system() != "Windows" or path.suffix.lower() in {".exe", ".com"}:
        return [str(path)]

    package = path.parent / "node_modules" / "@openai" / "codex"
    script = package / "bin" / "codex.js"
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    target = "aarch64-pc-windows-msvc" if architecture == "arm64" else "x86_64-pc-windows-msvc"
    dependency = f"codex-win32-{architecture}"
    binaries = [
        package / "node_modules" / "@openai" / dependency / "vendor" / target / "bin" / "codex.exe",
        package.parent / dependency / "vendor" / target / "bin" / "codex.exe",
    ]
    for binary in binaries:
        if binary.is_file():
            return [str(binary.resolve())]
    if script.is_file():
        local_node = path.parent / "node.exe"
        node = str(local_node.resolve()) if local_node.is_file() else shutil.which("node.exe")
        if node:
            return [str(Path(node).resolve()), str(script.resolve())]
    raise ValueError(
        "Codex Windows 실행 파일을 찾지 못했습니다. npm @openai/codex 설치를 확인하거나 "
        "CODEX_COMMAND에 codex.exe의 전체 경로를 지정해 주세요."
    )


def _child_environment() -> dict[str, str]:
    excluded = {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"}
    return {key: value for key, value in os.environ.items() if key.upper() not in excluded}


class CodexOAuthClient:
    def __init__(
        self, command: str = "codex", model: str = "", timeout_seconds: int = 180, runner=None
    ):
        if not isinstance(command, str) or not command.strip():
            raise ValueError("CODEX_COMMAND에 Codex 실행 파일을 지정해 주세요.")
        if timeout_seconds <= 0:
            raise ValueError("CODEX_TIMEOUT_SECONDS는 0보다 커야 합니다.")
        self.command = command
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run

    def _run(self, arguments: list[str], directory: str, prompt: str = ""):
        options = {
            "cwd": directory,
            "env": _child_environment(),
            "input": prompt,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "capture_output": True,
            "timeout": self.timeout_seconds,
            "shell": False,
            "check": False,
        }
        if platform.system() == "Windows":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            return self.runner(_resolve_command(self.command) + arguments, **options)
        except subprocess.TimeoutExpired:
            raise CodexOAuthError(
                f"Codex ChatGPT 요청이 {self.timeout_seconds}초 안에 끝나지 않았습니다. 잠시 후 다시 시도해 주세요."
            ) from None
        except (OSError, ValueError):
            raise CodexOAuthError(
                "Codex CLI 실행에 실패했습니다. CODEX_COMMAND 경로와 CLI 설치를 확인해 주세요."
            ) from None

    def check_login(self) -> bool:
        """Only accept the CLI's ChatGPT login status; never inspect its auth cache."""
        try:
            with tempfile.TemporaryDirectory(prefix="wedding-codex-login-") as directory:
                result = self._run(["login", "status"], directory)
        except CodexOAuthError as exc:
            raise ValueError(str(exc)) from None
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        lines = {line.strip().lower() for line in output.splitlines()}
        if result.returncode == 0 and "logged in using chatgpt" in lines:
            return True
        if "api key" in output.lower() or "api_key" in output.lower():
            raise ValueError(
                "현재 Codex 인증은 API 키 방식입니다. 이 도우미는 ChatGPT OAuth만 사용합니다. "
                "터미널에서 codex login으로 ChatGPT 로그인 후 다시 실행해 주세요."
            )
        raise ValueError(
            "Codex의 ChatGPT 로그인을 확인할 수 없습니다. 터미널에서 codex login을 완료하고 "
            "codex login status가 'Logged in using ChatGPT'인지 확인해 주세요."
        )

    def complete_json(self, prompt: str, schema: dict) -> dict:
        if not isinstance(prompt, str) or not prompt.strip():
            raise CodexOAuthError("Codex에 전달할 프롬프트가 비어 있습니다.")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise CodexOAuthError("Codex 출력 스키마는 type=object인 JSON Schema여야 합니다.")
        try:
            self.check_login()
        except ValueError as exc:
            raise CodexOAuthError(str(exc)) from None
        with tempfile.TemporaryDirectory(prefix="wedding-codex-") as directory:
            schema_path = Path(directory) / "output-schema.json"
            output_path = Path(directory) / "last-message.json"
            try:
                schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            except (OSError, TypeError, ValueError):
                raise CodexOAuthError("Codex 출력 스키마 파일을 준비하지 못했습니다.") from None
            arguments = [
                "exec", "--ignore-user-config", "--ephemeral", "--sandbox", "read-only",
                "--skip-git-repo-check", "--output-schema", str(schema_path),
                "-o", str(output_path), "--json", "--color", "never",
                "-c", 'forced_login_method="chatgpt"',
                "-c", "features.shell_tool=false",
                "-c", 'web_search="disabled"',
                "-c", "apps._default.enabled=false",
                "-c", "project_doc_max_bytes=0",
            ]
            if self.model:
                arguments.extend(["--model", self.model])
            arguments.append("-")
            result = self._run(arguments, directory, prompt)
            if result.returncode != 0:
                raise CodexOAuthError(
                    f"Codex ChatGPT 실행이 실패했습니다(exit={result.returncode}). "
                    "로그인 상태, 사용 한도, 네트워크 및 CLI 버전을 확인해 주세요. API 키로 대체하지 않았습니다."
                )
            try:
                value = json.loads(output_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                raise CodexOAuthError(
                    "Codex가 유효한 JSON 결과 파일을 남기지 않았습니다. 이 응답은 조사 결과로 저장하지 않습니다."
                ) from None
            if not isinstance(value, dict):
                raise CodexOAuthError("Codex 결과가 JSON 객체가 아닙니다. 이 응답은 조사 결과로 저장하지 않습니다.")
            return value

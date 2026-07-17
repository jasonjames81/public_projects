"""CLI adapters: shell out to a logged-in AI CLI (claude / gemini / codex).

No API key — auth is the CLI's own login. The Claude adapter keeps the
neutral-cwd trick so the repo's CLAUDE.md / auto-memory never bloat the
subprocess context.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile

from providers.base import Provider, ProviderError, ProviderInfo, estimate_tier

_NEUTRAL_CWD = tempfile.gettempdir()


class _CliProvider(Provider):
    binary: str = ""
    display_name: str = ""
    base_args: list[str] = []
    model_flag: str | None = None
    neutral_cwd: bool = False

    def __init__(self, *, model: str | None, timeout: int, retries: int = 1):
        self.model = model
        self.timeout = timeout
        self.retries = retries
        tier, verified = estimate_tier(model, "cli")
        present = shutil.which(self.binary) is not None
        self.info = ProviderInfo(
            name=self._name(),
            display_name=self.display_name,
            kind="cli",
            available=present,
            detail=(
                f"found on PATH — may require `{self.binary}` login"
                if present
                else f"{self.binary} not found on PATH"
            ),
            tier=tier,
            model=model or "(CLI default)",
            tier_verified=verified,
        )

    @classmethod
    def _name(cls) -> str:
        return f"{cls.binary}_cli"

    def _build_cmd(self) -> list[str]:
        cmd = [self.binary, *self.base_args]
        if self.model and self.model_flag:
            cmd += [self.model_flag, self.model]
        return cmd

    def generate(self, prompt: str) -> str:
        cmd = self._build_cmd()
        cwd = _NEUTRAL_CWD if self.neutral_cwd else None
        last_error: str | None = None
        for attempt in range(self.retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=cwd,
                )
            except FileNotFoundError:
                raise ProviderError(
                    f"{self.binary} CLI not found on PATH. Install it or pick another provider."
                ) from None
            except subprocess.TimeoutExpired:
                last_error = f"timed out after {self.timeout}s"
            else:
                if result.returncode != 0:
                    last_error = (
                        f"exit {result.returncode}: "
                        f"{result.stderr.strip() or '(no stderr)'}"
                    )
                elif not result.stdout.strip():
                    last_error = "empty stdout"
                else:
                    return result.stdout.strip()
            if attempt < self.retries:
                print(
                    f"[{self.binary}] attempt {attempt + 1} failed ({last_error}); retrying...",
                    file=sys.stderr,
                )
        raise ProviderError(
            f"{self.binary} CLI failed: {last_error}. "
            f"Try `{self.binary} login` or pick another provider."
        )


class ClaudeCli(_CliProvider):
    binary = "claude"
    display_name = "Claude Code (CLI login)"
    base_args = ["--print", "--no-session-persistence"]
    model_flag = "--model"
    neutral_cwd = True


class GeminiCli(_CliProvider):
    binary = "gemini"
    display_name = "Gemini (CLI login)"
    base_args = ["-p", "-"]
    model_flag = "-m"


class CodexCli(_CliProvider):
    binary = "codex"
    display_name = "Codex (CLI login)"
    base_args = ["exec", "-"]
    model_flag = "-m"

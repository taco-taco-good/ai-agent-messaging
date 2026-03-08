from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from agent_messaging.core.models import ModelOption
from agent_messaging.providers.base import ProviderError
from agent_messaging.providers.subprocess_cli import SubprocessCLIWrapper


class GeminiWrapper(SubprocessCLIWrapper):
    provider_name = "gemini"
    default_command = "gemini"
    default_supported_commands = ("/help", "/stats", "/model", "/models")
    default_model_catalog = (
        ModelOption(
            value="auto-gemini-3",
            label="Auto (Gemini 3)",
            description="Preview route when Gemini 3 access is enabled",
        ),
        ModelOption(
            value="auto-gemini-2.5",
            label="Auto (Gemini 2.5)",
            description="Let Gemini CLI choose between gemini-2.5-pro and gemini-2.5-flash",
        ),
        ModelOption(
            value="gemini-2.5-pro",
            label="gemini-2.5-pro",
            description="Best for harder reasoning and planning tasks",
        ),
        ModelOption(
            value="gemini-2.5-flash",
            label="gemini-2.5-flash",
            description="Fast general-purpose model",
        ),
        ModelOption(
            value="gemini-2.5-flash-lite",
            label="gemini-2.5-flash-lite",
            description="Cheapest and fastest lightweight option",
        ),
    )
    default_model_options = tuple(option.value for option in default_model_catalog)

    def __init__(
        self,
        executable: Optional[str] = None,
        default_model: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
        base_args: Optional[Sequence[str]] = None,
        model_options: Optional[Sequence[str]] = None,
        use_pty: bool = True,
        config_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(
            executable=executable or self.default_command,
            default_model=default_model,
            workspace_dir=workspace_dir,
            base_args=base_args,
            supported_commands=self.default_supported_commands,
            model_options=model_options or self.default_model_options,
            use_pty=use_pty,
            prompt_args=("--output-format", "json", "-p"),
            model_args_builder=lambda model: ["-m", model],
            output_parser=_parse_gemini_json_output,
            reset_session_on_model_change=True,
        )
        self.model_catalog = tuple(self.default_model_catalog)
        self.config_dir = config_dir or (Path.home() / ".gemini")

    async def _after_one_shot_success(self, raw_output: str, parsed_output: str) -> None:
        del raw_output
        del parsed_output
        self._refresh_resolved_model_from_chat_log()

    async def stats_response(self) -> str:
        self._refresh_resolved_model_from_chat_log()
        return self.format_stats_response()

    def _refresh_resolved_model_from_chat_log(self) -> None:
        if self.workspace_dir is None:
            return
        chats_dir = self.config_dir / "tmp" / "gemini" / "chats"
        if not chats_dir.exists():
            return
        project_hash = hashlib.sha256(
            str(self.workspace_dir.expanduser().resolve()).encode("utf-8")
        ).hexdigest()
        matched_payload = None
        latest_updated = ""
        for path in chats_dir.glob("session-*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("projectHash") != project_hash:
                continue
            session_id = str(payload.get("sessionId") or "")
            if self.provider_session_id and session_id == self.provider_session_id:
                matched_payload = payload
                break
            last_updated = str(payload.get("lastUpdated") or "")
            if last_updated >= latest_updated:
                latest_updated = last_updated
                matched_payload = payload
        if not isinstance(matched_payload, dict):
            return
        messages = matched_payload.get("messages")
        if not isinstance(messages, list):
            return
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            if message.get("type") != "gemini":
                continue
            model = message.get("model")
            if isinstance(model, str) and model:
                last_updated = matched_payload.get("lastUpdated")
                if self._exact_model_pending_since is not None and isinstance(last_updated, str):
                    try:
                        observed_ts = datetime.fromisoformat(
                            last_updated.replace("Z", "+00:00")
                        ).timestamp()
                    except ValueError:
                        observed_ts = None
                    if observed_ts is not None and observed_ts < self._exact_model_pending_since:
                        return
                session_id = matched_payload.get("sessionId")
                self.set_resolved_model(
                    model,
                    "gemini chat log",
                    session_id=session_id if isinstance(session_id, str) else None,
                )
                return


def _parse_gemini_json_output(output: str) -> str:
    text = output.strip()
    if not text:
        return ""

    decoder = json.JSONDecoder()
    payload = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (
            "response" in candidate or "error" in candidate or "session_id" in candidate
        ):
            payload = candidate
    if payload is None:
        return text
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message == "[object Object]" or not message:
            for marker in (
                "ModelNotFoundError:",
                "Error when talking to Gemini API",
            ):
                location = text.find(marker)
                if location >= 0:
                    message = text[location:].splitlines()[0].strip()
                    break
        if message:
            raise ProviderError(message)
    response = payload.get("response")
    if response is None:
        return text
    return str(response)

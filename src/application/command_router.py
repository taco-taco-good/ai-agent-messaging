from __future__ import annotations

from typing import Dict, Iterable, Optional

from agent_messaging.core.errors import CommandValidationError
from agent_messaging.core.models import RoutedCLICommand, RuntimeCommand


class CommandRouter:
    def __init__(self, whitelist: Iterable[str] = ("/help", "/stats", "/model", "/models")) -> None:
        self.whitelist = frozenset(whitelist)
        self.aliases = {
            "help": "/help",
            "/help": "/help",
            "stats": "/stats",
            "/stats": "/stats",
            "model": "/model",
            "/model": "/model",
            "models": "/models",
            "/models": "/models",
        }

    def build_runtime_command(
        self,
        kind: str,
        agent_id: str,
        session_key: str,
        channel_id: str,
        is_dm: bool,
        payload: Dict[str, object],
        parent_channel_id: Optional[str] = None,
    ) -> RuntimeCommand:
        return RuntimeCommand(
            kind=kind,
            agent_id=agent_id,
            session_key=session_key,
            channel_id=channel_id,
            parent_channel_id=parent_channel_id,
            is_dm=is_dm,
            payload=dict(payload),
        )

    def parse_cli_command(
        self,
        raw_command: str,
        interaction_payload: Optional[Dict[str, object]] = None,
    ) -> RoutedCLICommand:
        normalized = (raw_command or "").strip()
        if not normalized:
            raise CommandValidationError("CLI command cannot be empty.")

        command = normalized.split()[0]
        command = self.aliases.get(command, command)
        if command not in self.whitelist:
            supported = ", ".join(sorted(self.whitelist))
            raise CommandValidationError(
                "Unsupported command: {0}. Supported commands: {1}".format(command, supported)
            )

        args = dict(interaction_payload or {})
        if command == "/model" and not args:
            return RoutedCLICommand(command=command, requires_interaction=True)
        return RoutedCLICommand(command=command, args=args)

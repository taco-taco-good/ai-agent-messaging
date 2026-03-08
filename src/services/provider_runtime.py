from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Callable, Dict, Optional, Tuple

from agent_messaging.core.interfaces import ProviderFactoryProtocol, SessionManagerProtocol
from agent_messaging.core.models import AgentConfig, ModelOption, SessionRecord, utc_now
from agent_messaging.observability.context import log_context
from agent_messaging.providers.base import CLIWrapper, ProviderError, ProviderStartupError


ProviderFactory = Callable[[AgentConfig, str, Optional[SessionRecord]], CLIWrapper]
logger = logging.getLogger(__name__)

_DEFAULT_WATCHDOG_INTERVAL = 30.0
_DEFAULT_MAX_RESTART_ATTEMPTS = 3
_DEFAULT_RESTART_BACKOFF_BASE = 1.0  # initial delay; doubles each attempt
_DEFAULT_IDLE_TIMEOUT = 3600.0  # seconds – stop idle wrappers after 1 hour

CrashCallback = Callable[[str, str, str], object]


class ProviderRuntime:
    def __init__(
        self,
        session_manager: SessionManagerProtocol,
        provider_factory: ProviderFactoryProtocol,
        *,
        watchdog_interval: float = _DEFAULT_WATCHDOG_INTERVAL,
        max_restart_attempts: int = _DEFAULT_MAX_RESTART_ATTEMPTS,
        restart_backoff_base: float = _DEFAULT_RESTART_BACKOFF_BASE,
        idle_timeout: float = _DEFAULT_IDLE_TIMEOUT,
        on_crash: Optional[CrashCallback] = None,
    ) -> None:
        self.session_manager = session_manager
        self.provider_factory = provider_factory
        self._watchdog_interval = watchdog_interval
        self._max_restart_attempts = max_restart_attempts
        self._restart_backoff_base = restart_backoff_base
        self._idle_timeout = idle_timeout
        self._on_crash = on_crash
        self._last_activity: Dict[Tuple[str, str], float] = {}

        self._wrappers: Dict[Tuple[str, str], CLIWrapper] = {}
        self._wrapper_configs: Dict[Tuple[str, str], AgentConfig] = {}
        self._restart_counts: Dict[Tuple[str, str], int] = {}
        self._session_locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._watchdog_task: Optional[asyncio.Task[None]] = None

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def start_watchdog(self) -> None:
        """Start background watchdog task. Safe to call multiple times."""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="provider_watchdog"
        )
        logger.info("watchdog_started", extra={"interval_seconds": self._watchdog_interval})

    async def _watchdog_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._watchdog_interval)
                await self._check_all_wrappers()
                await self._cleanup_idle_wrappers()
            except asyncio.CancelledError:
                logger.info("watchdog_cancelled")
                return
            except Exception:
                logger.exception("watchdog_unexpected_error")

    async def _check_all_wrappers(self) -> None:
        for key in list(self._wrappers.keys()):
            wrapper = self._wrappers.get(key)
            if wrapper is None or wrapper.is_alive():
                continue
            agent_id, session_key = key
            logger.warning(
                "watchdog_dead_wrapper",
                extra={"agent_id": agent_id, "session_key": session_key},
            )
            await self._try_restart(key, reason="watchdog_detected_crash")

    async def _cleanup_idle_wrappers(self) -> None:
        now = _time.monotonic()
        for key in list(self._wrappers.keys()):
            last = self._last_activity.get(key)
            if last is None:
                continue
            idle_seconds = now - last
            if idle_seconds < self._idle_timeout:
                continue
            agent_id, session_key = key
            wrapper = self._wrappers.get(key)
            if wrapper is None:
                continue
            logger.info(
                "idle_wrapper_cleanup",
                extra={"agent_id": agent_id, "session_key": session_key, "idle_seconds": idle_seconds},
            )
            self._wrappers.pop(key, None)
            self._wrapper_configs.pop(key, None)
            self._restart_counts.pop(key, None)
            self._session_locks.pop(key, None)
            self._last_activity.pop(key, None)
            try:
                await wrapper.stop()
            except Exception:
                logger.exception("idle_wrapper_stop_error", extra={"agent_id": agent_id})

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    async def _try_restart(
        self,
        wrapper_key: Tuple[str, str],
        *,
        reason: str = "crash",
    ) -> Optional[CLIWrapper]:
        agent_id, session_key = wrapper_key
        count = self._restart_counts.get(wrapper_key, 0) + 1
        self._restart_counts[wrapper_key] = count

        if count > self._max_restart_attempts:
            logger.error(
                "provider_restart_exhausted",
                extra={"agent_id": agent_id, "session_key": session_key, "attempts": count - 1},
            )
            self._wrappers.pop(wrapper_key, None)
            self._wrapper_configs.pop(wrapper_key, None)
            if self._on_crash:
                self._on_crash(
                    agent_id, session_key,
                    "자동 재시작 횟수({0}회)를 초과했습니다. 수동 확인이 필요합니다.".format(self._max_restart_attempts),
                )
            return None

        backoff = self._restart_backoff_base * (2 ** (count - 1))
        logger.info(
            "provider_restart_attempt",
            extra={"agent_id": agent_id, "session_key": session_key, "attempt": count, "backoff_seconds": backoff, "reason": reason},
        )
        await asyncio.sleep(backoff)

        agent = self._wrapper_configs.get(wrapper_key)
        if agent is None:
            logger.error("provider_restart_no_config", extra={"agent_id": agent_id, "session_key": session_key})
            return None

        existing_session = await self.session_manager.get(
            channel_id=session_key,
            is_dm=session_key.startswith("discord:dm:"),
        )
        try:
            wrapper = self.provider_factory(agent, session_key, existing_session)
            await wrapper.start()
        except (ProviderStartupError, ProviderError, OSError) as exc:
            logger.error(
                "provider_restart_failed",
                extra={"agent_id": agent_id, "session_key": session_key, "attempt": count, "error": str(exc)},
            )
            return await self._try_restart(wrapper_key, reason=reason)

        self._wrappers[wrapper_key] = wrapper
        logger.info(
            "provider_restarted",
            extra={"agent_id": agent_id, "session_key": session_key, "attempt": count, "provider_session_id": wrapper.provider_session_id},
        )
        if self._on_crash:
            self._on_crash(
                agent_id, session_key,
                "에이전트가 재시작되었습니다. (시도 {0}/{1})".format(count, self._max_restart_attempts),
            )
        return wrapper

    # ------------------------------------------------------------------
    # Session-level concurrency control
    # ------------------------------------------------------------------

    def session_lock(self, agent_id: str, session_key: str) -> asyncio.Lock:
        """Return a per-session lock to serialize message handling."""
        key = (agent_id, session_key)
        lock = self._session_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[key] = lock
        return lock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_wrapper(
        self,
        agent: AgentConfig,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str],
    ) -> Tuple[str, CLIWrapper]:
        session_key = self.session_manager.session_scope_key(
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        wrapper_key = (agent.agent_id, session_key)
        wrapper = self._wrappers.get(wrapper_key)

        if wrapper is not None and wrapper.is_alive():
            self._restart_counts.pop(wrapper_key, None)
            self._last_activity[wrapper_key] = _time.monotonic()
            return session_key, wrapper

        # Dead wrapper – try crash recovery
        if wrapper is not None and not wrapper.is_alive():
            logger.warning("provider_dead_on_message", extra={"agent_id": agent.agent_id, "session_key": session_key})
            self._wrapper_configs[wrapper_key] = agent
            recovered = await self._try_restart(wrapper_key, reason="dead_on_message")
            if recovered is not None:
                return session_key, recovered

        # Fresh start
        existing_session = await self.session_manager.get(
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        with log_context(
            agent_id=agent.agent_id,
            session_key=session_key,
            provider=agent.provider,
            provider_session_id=existing_session.provider_session_id if existing_session else "-",
        ):
            logger.info("provider_wrapper_start")
            wrapper = self.provider_factory(agent, session_key, existing_session)
            await wrapper.start()
            self._wrappers[wrapper_key] = wrapper
            self._wrapper_configs[wrapper_key] = agent
            self._restart_counts.pop(wrapper_key, None)
            self._last_activity[wrapper_key] = _time.monotonic()
            with log_context(provider_session_id=wrapper.provider_session_id or session_key):
                await self.session_manager.upsert(
                    channel_id=channel_id,
                    is_dm=is_dm,
                    parent_channel_id=parent_channel_id,
                    agent_id=agent.agent_id,
                    provider=agent.provider,
                    provider_session_id=wrapper.provider_session_id or "",
                    current_model=wrapper.current_model or agent.model,
                )
        return session_key, wrapper

    async def stop_session(
        self,
        agent_id: str,
        session_key: str,
    ) -> None:
        wrapper_key = (agent_id, session_key)
        wrapper = self._wrappers.pop(wrapper_key, None)
        self._wrapper_configs.pop(wrapper_key, None)
        self._restart_counts.pop(wrapper_key, None)
        self._session_locks.pop(wrapper_key, None)
        self._last_activity.pop(wrapper_key, None)
        if wrapper is not None:
            await wrapper.stop()

    async def shutdown(self) -> None:
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        wrappers = list(self._wrappers.values())
        self._wrappers.clear()
        self._wrapper_configs.clear()
        self._restart_counts.clear()
        self._session_locks.clear()
        self._last_activity.clear()
        for wrapper in wrappers:
            await wrapper.stop()

    async def options_for(
        self,
        agent: AgentConfig,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> list[ModelOption]:
        session_key, wrapper = await self.ensure_wrapper(
            agent=agent,
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        lock = self.session_lock(agent.agent_id, session_key)
        catalog = list(wrapper.available_model_catalog())
        if catalog:
            return catalog
        if wrapper.supports_native_command("/models"):
            try:
                async with lock:
                    response = await self._collect(wrapper.send_native_command("/models"))
                parsed = self._parse_model_options(response)
                if parsed:
                    return parsed
            except Exception:
                logger.exception(
                    "provider_model_options_fetch_failed",
                    extra={"agent_id": agent.agent_id, "session_key": session_key},
                )
        return [
            ModelOption(value=option, label=option)
            for option in wrapper.available_model_options()
        ]

    async def _collect(self, stream) -> str:
        parts = []
        async for piece in stream:
            parts.append(piece)
        return "".join(parts)

    @staticmethod
    def _parse_model_options(response: str) -> list[ModelOption]:
        options: list[ModelOption] = []
        for raw_line in response.replace(",", "\n").splitlines():
            line = raw_line.strip()
            line = line.lstrip("-*").strip()
            if not line or line.startswith("model:") or line.startswith("stats:"):
                continue
            options.append(ModelOption(value=line, label=line))
        # Preserve order while dropping duplicates
        seen = set()
        result: list[ModelOption] = []
        for option in options:
            if option.value in seen:
                continue
            seen.add(option.value)
            result.append(option)
        return result

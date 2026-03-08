"""Tests for stability features: crash recovery, watchdog, session lock, idle cleanup."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

from agent_messaging.core.models import AgentConfig, FrontmatterMetadata
from agent_messaging.core.registry import AgentRegistry
from agent_messaging.providers.base import CLIWrapper, ProviderStartupError
from agent_messaging.runtime.session_manager import SessionManager
from agent_messaging.runtime.session_store import SessionStore
from agent_messaging.services import ProviderRuntime
from agent_messaging.services.conversation import ConversationService


class _FakeProvider(CLIWrapper):
    provider_name = "fake"
    supported_commands = ("/help", "/stats", "/model", "/models")
    model_options = ("alpha", "beta")

    def __init__(self, default_model=None, *, crash_after: int = 0):
        super().__init__(default_model=default_model)
        self._alive = False
        self._crash_after = crash_after
        self._send_count = 0
        self.started_count = 0

    async def start(self) -> None:
        self._alive = True
        self.started_count += 1
        self.provider_session_id = "session-{0}".format(self.started_count)

    async def send_user_message(self, message: str):
        self._send_count += 1
        if self._crash_after and self._send_count >= self._crash_after:
            self._alive = False
        yield "reply:{0}".format(message)

    async def send_native_command(self, command: str, args=None):
        if command == "/models":
            yield "alpha\nbeta"
            return
        yield command

    async def reset_session(self) -> None:
        self._alive = False

    async def stop(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def kill(self) -> None:
        """Simulate a crash."""
        self._alive = False


def _make_runtime(
    tempdir: str,
    *,
    crash_after: int = 0,
    max_restart_attempts: int = 3,
    restart_backoff_base: float = 0.01,
    watchdog_interval: float = 0.1,
    idle_timeout: float = 3600.0,
    on_crash=None,
    start_fails_until: int = 0,
) -> Tuple[ProviderRuntime, AgentConfig, AgentRegistry]:
    agent = AgentConfig(
        agent_id="reviewer",
        provider="codex",
        discord_token="token",
        workspace_dir=Path(tempdir) / "workspace" / "reviewer",
        memory_dir=Path(tempdir) / "memory",
        model="alpha",
        display_name="Reviewer",
    )
    registry = AgentRegistry({"reviewer": agent})
    store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
    session_manager = SessionManager(store)

    fail_count = [0]

    def factory(config, session_key, session_record=None):
        if start_fails_until and fail_count[0] < start_fails_until:
            fail_count[0] += 1
            raise ProviderStartupError("simulated startup failure")
        return _FakeProvider(
            default_model=config.model,
            crash_after=crash_after,
        )

    runtime = ProviderRuntime(
        session_manager=session_manager,
        provider_factory=factory,
        watchdog_interval=watchdog_interval,
        max_restart_attempts=max_restart_attempts,
        restart_backoff_base=restart_backoff_base,
        idle_timeout=idle_timeout,
        on_crash=on_crash,
    )
    return runtime, agent, registry


class CrashRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_dead_wrapper_is_restarted_on_next_message(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(tempdir)
            _, wrapper1 = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertTrue(wrapper1.is_alive())

            # Simulate crash
            wrapper1.kill()  # type: ignore[attr-defined]
            self.assertFalse(wrapper1.is_alive())

            # Next message should trigger restart
            _, wrapper2 = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertTrue(wrapper2.is_alive())
            self.assertIsNot(wrapper1, wrapper2)

    async def test_restart_exhaustion_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            crash_reasons: List[str] = []
            runtime, agent, _ = _make_runtime(
                tempdir,
                max_restart_attempts=2,
                start_fails_until=999,  # always fail
                on_crash=lambda a, s, r: crash_reasons.append(r),
            )
            # Manually put a dead wrapper in
            fake = _FakeProvider(default_model="alpha")
            await fake.start()
            fake.kill()
            key = ("reviewer", "discord:channel:1")
            runtime._wrappers[key] = fake
            runtime._wrapper_configs[key] = agent

            result = await runtime._try_restart(key, reason="test")
            self.assertIsNone(result)
            self.assertTrue(any("초과" in r for r in crash_reasons))

    async def test_restart_count_resets_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(tempdir)
            _, w = await runtime.ensure_wrapper(agent, "1", False, None)
            key = ("reviewer", "discord:channel:1")
            self.assertNotIn(key, runtime._restart_counts)

            # Crash and recover
            w.kill()  # type: ignore[attr-defined]
            _, w2 = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertTrue(w2.is_alive())

            # Use again – restart count should be reset
            _, w3 = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertNotIn(key, runtime._restart_counts)


class WatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_watchdog_detects_and_restarts_dead_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            crash_notifications: List[str] = []
            runtime, agent, _ = _make_runtime(
                tempdir,
                watchdog_interval=0.05,
                on_crash=lambda a, s, r: crash_notifications.append(r),
            )
            _, wrapper = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertTrue(wrapper.is_alive())

            runtime.start_watchdog()
            # Crash the wrapper
            wrapper.kill()  # type: ignore[attr-defined]

            # Wait for watchdog to detect and restart
            await asyncio.sleep(0.2)
            key = ("reviewer", "discord:channel:1")
            new_wrapper = runtime._wrappers.get(key)
            self.assertIsNotNone(new_wrapper)
            self.assertTrue(new_wrapper.is_alive())  # type: ignore[union-attr]
            self.assertIsNot(wrapper, new_wrapper)

            await runtime.shutdown()

    async def test_watchdog_stops_on_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(tempdir, watchdog_interval=0.05)
            runtime.start_watchdog()
            self.assertFalse(runtime._watchdog_task.done())  # type: ignore[union-attr]
            await runtime.shutdown()
            self.assertIsNone(runtime._watchdog_task)


class SessionLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_lock_serializes_access(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, registry = _make_runtime(tempdir)
            service = ConversationService(
                registry=registry,
                session_manager=runtime.session_manager,
                provider_runtime=runtime,
            )

            # Send two messages concurrently – they should be serialized
            results = await asyncio.gather(
                service.handle_user_message(
                    agent_id="reviewer", channel_id="1", content="msg1",
                    is_dm=False,
                    metadata=FrontmatterMetadata(tags=["t"], topic="T", summary="S"),
                ),
                service.handle_user_message(
                    agent_id="reviewer", channel_id="1", content="msg2",
                    is_dm=False,
                    metadata=FrontmatterMetadata(tags=["t"], topic="T", summary="S"),
                ),
            )
            # Both should succeed (no interleaving crash)
            self.assertEqual(results[0], ["reply:msg1"])
            self.assertEqual(results[1], ["reply:msg2"])

    async def test_different_channels_have_separate_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(tempdir)
            lock1 = runtime.session_lock("reviewer", "discord:channel:1")
            lock2 = runtime.session_lock("reviewer", "discord:channel:2")
            self.assertIsNot(lock1, lock2)


class IdleCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_wrapper_is_cleaned_up(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(
                tempdir,
                watchdog_interval=0.05,
                idle_timeout=0.1,  # very short for testing
            )
            _, wrapper = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertTrue(wrapper.is_alive())

            runtime.start_watchdog()

            # Wait long enough for idle timeout + watchdog check
            await asyncio.sleep(0.3)

            key = ("reviewer", "discord:channel:1")
            self.assertNotIn(key, runtime._wrappers)

            await runtime.shutdown()

    async def test_active_wrapper_is_not_cleaned_up(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(
                tempdir,
                watchdog_interval=0.05,
                idle_timeout=10.0,  # long timeout
            )
            _, wrapper = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertTrue(wrapper.is_alive())

            runtime.start_watchdog()
            await asyncio.sleep(0.15)

            key = ("reviewer", "discord:channel:1")
            self.assertIn(key, runtime._wrappers)

            await runtime.shutdown()


class StopSessionCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_session_clears_all_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime, agent, _ = _make_runtime(tempdir)
            _, wrapper = await runtime.ensure_wrapper(agent, "1", False, None)
            key = ("reviewer", "discord:channel:1")

            # Create a lock
            runtime.session_lock("reviewer", "discord:channel:1")
            self.assertIn(key, runtime._session_locks)

            await runtime.stop_session("reviewer", "discord:channel:1")

            self.assertNotIn(key, runtime._wrappers)
            self.assertNotIn(key, runtime._wrapper_configs)
            self.assertNotIn(key, runtime._restart_counts)
            self.assertNotIn(key, runtime._session_locks)
            self.assertNotIn(key, runtime._last_activity)

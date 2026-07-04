"""Tests for the mount-lazy + idempotent behaviour of :mod:`api_mount`.

These tests mock ``astrbot.dashboard.server.APP`` to simulate the
startup-timing scenario where ``APP is None`` during plugin
initialization but becomes available later when a tool is first called.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

# Module-under-test helpers (public test API)
from astrbot_plugin_ask_user_choice.api_mount import (
    _get_mount_state,
    _mount_api_router,
    _reset_mount_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_server_module(app_value: object) -> types.ModuleType:
    """Build a fake ``astrbot.dashboard.server`` module."""
    mod = types.ModuleType("astrbot.dashboard.server")
    mod.APP = app_value
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_mount():
    """Reset the mount-state globals before every test."""
    _reset_mount_state()
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mount_returns_false_when_app_is_none(monkeypatch):
    """Simulate plugin init: dashboard hasn't started yet, APP is None."""
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(None),
    )
    assert _mount_api_router() is False
    state = _get_mount_state()
    assert state["mounted"] is False
    assert state["warned"] is False  # No warning logged when APP is None


def test_mount_returns_false_when_app_missing_private_app(monkeypatch):
    """Dashboard APP object exists but has no _app (unexpected shape)."""
    app_mock = MagicMock()
    del app_mock._app  # Ensure attribute does not exist
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(app_mock),
    )
    assert _mount_api_router() is False
    state = _get_mount_state()
    assert state["mounted"] is False
    assert state["warned"] is True  # Non-transient shape error → warn once


def test_mount_succeeds(monkeypatch):
    """Dashboard is fully up: mount successfully adds the router."""
    underlying = FastAPI()
    app_mock = MagicMock()
    app_mock._app = underlying
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(app_mock),
    )

    pre_count = len(underlying.routes)
    assert _mount_api_router() is True
    state = _get_mount_state()
    assert state["mounted"] is True
    assert state["warned"] is False

    # Verify the router was added (route count increased)
    assert len(underlying.routes) > pre_count, (
        f"expected route count > {pre_count}, got {len(underlying.routes)}"
    )


def test_mount_is_idempotent(monkeypatch):
    """Calling mount after a successful mount is a no-op and returns True."""
    underlying = FastAPI()
    app_mock = MagicMock()
    app_mock._app = underlying
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(app_mock),
    )

    assert _mount_api_router() is True
    assert _get_mount_state()["mounted"] is True

    # Second call — should return True without re-import or re-mount
    assert _mount_api_router() is True
    # Underlying should have the routes added only once
    route_count = len(underlying.routes)
    assert _mount_api_router() is True  # third call: still True, same count
    assert len(underlying.routes) == route_count


def test_mount_retry_after_transient_failure(monkeypatch):
    """First call returns False (APP None), then succeeds on retry."""
    # --- Phase 1: APP is None (plugin init) ---
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(None),
    )
    assert _mount_api_router() is False

    # --- Phase 2: dashboard becomes available ---
    underlying = FastAPI()
    app_mock = MagicMock()
    app_mock._app = underlying
    # Replace the mock module — the function re-imports from sys.modules
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(app_mock),
    )
    assert _mount_api_router() is True
    assert _get_mount_state()["mounted"] is True


def test_warn_emitted_only_once_on_persistent_error(monkeypatch):
    """Persistent shape error emits a warning on the first call only."""
    app_mock = MagicMock()
    del app_mock._app  # AttributeError persists
    monkeypatch.setitem(
        __import__("sys").modules,
        "astrbot.dashboard.server",
        _mock_server_module(app_mock),
    )

    assert _mount_api_router() is False
    assert _get_mount_state()["warned"] is True

    # Second call — returns False but no extra warning (state unchanged)
    assert _mount_api_router() is False
    assert _get_mount_state()["warned"] is True

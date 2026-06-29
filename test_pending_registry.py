"""PendingRegistry 单元测试。

Author: elecvoid243
Date: 2026-06-29
Spec: docs/superpowers/specs/2026-06-29-ask-user-choice-suspension-design.md §4.3 / §9.2
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from pending_registry import PendingRegistry, PendingRequest


@pytest.mark.asyncio
async def test_register_resolve_basic():
    reg = PendingRegistry()
    key = ("umo:x", "sender:1")
    fut = asyncio.get_event_loop().create_future()
    req = PendingRequest(key=key, future=fut, prompt="p")
    reg.register(req)

    assert reg.has_pending(key) is True
    assert reg.try_resolve(key, "A") is True
    assert fut.result() == "A"
    assert reg.has_pending(key) is False


@pytest.mark.asyncio
async def test_created_at_is_monotonic():
    reg = PendingRegistry()
    fut = asyncio.get_event_loop().create_future()
    before = __import__("time").monotonic()
    req = PendingRequest(key=("u", "s"), future=fut, prompt="p")
    after = __import__("time").monotonic()
    assert before <= req.created_at <= after


@pytest.mark.asyncio
async def test_resolve_unknown_key_returns_false():
    reg = PendingRegistry()
    assert reg.try_resolve(("nope", "0"), "A") is False


@pytest.mark.asyncio
async def test_resolve_already_resolved_returns_false():
    reg = PendingRegistry()
    key = ("umo", "s")
    fut = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut, prompt="p"))
    fut.set_result("first")
    assert reg.try_resolve(key, "second") is False
    assert reg.has_pending(key) is False  # 已 pop


@pytest.mark.asyncio
async def test_pending_id_is_unique():
    reg = PendingRegistry()
    ids: set[str] = set()
    for i in range(5):
        fut = asyncio.get_event_loop().create_future()
        req = PendingRequest(key=(f"umo{i}", f"s{i}"), future=fut, prompt="p")
        reg.register(req)
        ids.add(req.pending_id)
    assert len(ids) == 5


@pytest.mark.asyncio
async def test_cancel():
    reg = PendingRegistry()
    key = ("umo", "s")
    fut = asyncio.get_event_loop().create_future()
    reg.register(PendingRequest(key=key, future=fut, prompt="p"))
    assert reg.cancel(key, reason="test") is True
    with pytest.raises(asyncio.CancelledError):
        fut.result()
    assert reg.has_pending(key) is False


@pytest.mark.asyncio
async def test_cancel_unknown_returns_false():
    reg = PendingRegistry()
    assert reg.cancel(("nope", "0"), reason="x") is False


@pytest.mark.asyncio
async def test_cleanup_all():
    reg = PendingRegistry()
    futures: list[asyncio.Future[str]] = []
    for i in range(3):
        fut = asyncio.get_event_loop().create_future()
        reg.register(PendingRequest(key=(f"umo{i}", f"s{i}"), future=fut, prompt="p"))
        futures.append(fut)
    reg.cleanup_all()
    for fut in futures:
        with pytest.raises(asyncio.CancelledError):
            fut.result()
    assert reg.has_pending(("umo0", "s0")) is False

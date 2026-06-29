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

"""Dual-axis venetian command sequencing tests.

Issue #33: a venetian instance owns BOTH set_cover_position AND
set_cover_tilt_position on a single HA entity. The work is split between:

  * ``CoverCommandService.apply_position`` — fires ``set_cover_position``
    and then calls ``context.policy.after_position_command``.
  * ``VenetianPolicy`` — owns a ``DualAxisSequencer`` that polls
    ``current_position`` until the cover settles, fires
    ``set_cover_tilt_position``, and answers
    ``is_in_tilt_suppression(entity_id)`` for manual_override.

The settle / suppression unit tests live in
``tests/test_managers/test_dual_axis_sequencer.py``; this file pins the
``apply_position`` ↔ policy contract end-to-end.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.adaptive_cover_pro.cover_types import VenetianPolicy
from custom_components.adaptive_cover_pro.managers.cover_command import (
    CoverCommandService,
    PositionContext,
)


@pytest.fixture
def hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    return h


@pytest.fixture
def svc(hass):
    s = CoverCommandService(
        hass=hass,
        logger=MagicMock(),
        cover_type="cover_venetian",
        grace_mgr=MagicMock(),
        open_close_threshold=50,
    )
    s._enabled = True
    return s


@pytest.fixture
def attached_policy(svc, hass):
    """Return a VenetianPolicy with a DualAxisSequencer attached and pre-stubbed."""
    policy = VenetianPolicy()
    policy.attach(
        hass=hass,
        logger=MagicMock(),
        grace_mgr=MagicMock(),
        get_current_position=svc._get_current_position,
        position_tolerance=5,
        is_dry_run=lambda: False,
    )
    # Skip the real polling loop — covered in dual_axis_sequencer unit tests.
    policy._sequencer._wait_for_position_settle = AsyncMock(return_value=(True, 60))
    return policy


def _ctx_venetian(policy, *, tilt: int | None) -> PositionContext:
    return PositionContext(
        auto_control=True,
        manual_override=False,
        sun_just_appeared=False,
        min_change=1,
        time_threshold=0,
        special_positions=[0, 100],
        force=True,  # Bypass delta/time gates for unit tests
        tilt=tilt,
        policy=policy,
    )


def _patch_caps_dual_axis():
    return patch(
        "custom_components.adaptive_cover_pro.managers.cover_command.check_cover_features",
        return_value={
            "has_set_position": True,
            "has_set_tilt_position": True,
            "has_open": True,
            "has_close": True,
            "has_stop": True,
        },
    )


def _state_with_position(pos: int):
    state = MagicMock()
    state.state = "open"
    state.attributes = {"current_position": pos, "current_tilt_position": 50}
    return state


@pytest.mark.asyncio
async def test_apply_position_emits_position_then_tilt(svc, hass, attached_policy):
    """Both services fire on a venetian apply_position with tilt set."""
    entity_id = "cover.venetian_kitchen"
    hass.states.get.return_value = _state_with_position(0)

    with _patch_caps_dual_axis():
        outcome, _ = await svc.apply_position(
            entity_id, 60, "solar", _ctx_venetian(attached_policy, tilt=80)
        )

    assert outcome == "sent"
    assert hass.services.async_call.call_count == 2
    services_called = [call.args[1] for call in hass.services.async_call.call_args_list]
    assert services_called == ["set_cover_position", "set_cover_tilt_position"]
    last_data = hass.services.async_call.call_args_list[-1].args[2]
    assert last_data["tilt_position"] == 80


@pytest.mark.asyncio
async def test_apply_position_stamps_suppression_window(svc, hass, attached_policy):
    """The position-axis command stamps the policy's suppression window."""
    entity_id = "cover.venetian_lounge"
    hass.states.get.return_value = _state_with_position(0)

    with _patch_caps_dual_axis():
        await svc.apply_position(
            entity_id, 40, "solar", _ctx_venetian(attached_policy, tilt=70)
        )

    assert attached_policy.is_in_tilt_suppression(entity_id) is True


@pytest.mark.asyncio
async def test_apply_position_skips_tilt_when_no_tilt_target(
    svc, hass, attached_policy
):
    """Without ``context.tilt``, only the position service fires."""
    entity_id = "cover.venetian_no_tilt"
    hass.states.get.return_value = _state_with_position(0)

    with _patch_caps_dual_axis():
        outcome, _ = await svc.apply_position(
            entity_id, 60, "solar", _ctx_venetian(attached_policy, tilt=None)
        )

    assert outcome == "sent"
    assert hass.services.async_call.call_count == 1
    assert hass.services.async_call.call_args_list[0].args[1] == "set_cover_position"


@pytest.mark.asyncio
async def test_apply_position_no_policy_skips_tilt_entirely(svc, hass):
    """When PositionContext.policy is None (non-venetian path), no tilt fires."""
    entity_id = "cover.kitchen"
    hass.states.get.return_value = _state_with_position(0)
    ctx = PositionContext(
        auto_control=True,
        manual_override=False,
        sun_just_appeared=False,
        min_change=1,
        time_threshold=0,
        special_positions=[0, 100],
        force=True,
        tilt=80,  # Set but ignored because policy is None
        policy=None,
    )

    with _patch_caps_dual_axis():
        outcome, _ = await svc.apply_position(entity_id, 60, "solar", ctx)

    assert outcome == "sent"
    assert hass.services.async_call.call_count == 1
    assert hass.services.async_call.call_args_list[0].args[1] == "set_cover_position"

"""Dual-axis venetian command sequencing tests for CoverCommandService.

Issue #33: a venetian instance owns BOTH set_cover_position AND
set_cover_tilt_position on a single HA entity. apply_position must:

  1. Send set_cover_position with the resolved position.
  2. Poll current_position until the cover settles or the timeout fires.
  3. Send set_cover_tilt_position with the engine-derived tilt.
  4. Stamp ``position_command_at`` so manual_override's tilt-suppression
     window covers the motor back-rotate.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.adaptive_cover_pro.const import (
    VENETIAN_TILT_SUPPRESSION_SECONDS,
)
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


def _ctx_venetian(*, tilt: int | None) -> PositionContext:
    return PositionContext(
        auto_control=True,
        manual_override=False,
        sun_just_appeared=False,
        min_change=1,
        time_threshold=0,
        special_positions=[0, 100],
        force=True,  # Bypass delta/time gates for unit tests
        is_venetian=True,
        tilt=tilt,
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
async def test_apply_position_emits_position_then_tilt(svc, hass) -> None:
    """Both services fire on a venetian apply_position with tilt set."""
    entity_id = "cover.venetian_kitchen"
    # Cover is at 0% (closed), the request is to move to 60% — non-trivial delta.
    hass.states.get.return_value = _state_with_position(0)

    with (
        _patch_caps_dual_axis(),
        patch.object(
            svc, "_wait_for_position_settle", new=AsyncMock(return_value=(True, 60))
        ),
    ):
        outcome, _ = await svc.apply_position(
            entity_id, 60, "solar", _ctx_venetian(tilt=80)
        )

    assert outcome == "sent"
    assert hass.services.async_call.call_count == 2
    services_called = [call.args[1] for call in hass.services.async_call.call_args_list]
    assert services_called == ["set_cover_position", "set_cover_tilt_position"]
    # Tilt service carries the requested tilt target
    last_data = hass.services.async_call.call_args_list[-1].args[2]
    assert last_data["tilt_position"] == 80


@pytest.mark.asyncio
async def test_position_command_at_stamped_for_tilt_suppression(svc, hass) -> None:
    """The position-axis command stamps the suppression window."""
    entity_id = "cover.venetian_lounge"
    hass.states.get.return_value = _state_with_position(0)

    with (
        _patch_caps_dual_axis(),
        patch.object(
            svc, "_wait_for_position_settle", new=AsyncMock(return_value=(True, 40))
        ),
    ):
        await svc.apply_position(entity_id, 40, "solar", _ctx_venetian(tilt=70))

    state = svc.state(entity_id)
    assert state.position_command_at is not None
    assert svc.is_in_venetian_tilt_suppression(entity_id) is True


def test_is_in_venetian_tilt_suppression_expires(svc) -> None:
    """The suppression window expires after VENETIAN_TILT_SUPPRESSION_SECONDS."""
    entity_id = "cover.venetian"
    state = svc.state(entity_id)
    state.position_command_at = dt.datetime.now(dt.UTC) - dt.timedelta(
        seconds=VENETIAN_TILT_SUPPRESSION_SECONDS + 1
    )
    assert svc.is_in_venetian_tilt_suppression(entity_id) is False


def test_is_in_venetian_tilt_suppression_unknown_entity(svc) -> None:
    """No prior position command means no suppression window."""
    assert svc.is_in_venetian_tilt_suppression("cover.never_touched") is False


@pytest.mark.asyncio
async def test_apply_position_skips_tilt_for_non_venetian_context(svc, hass) -> None:
    """Without is_venetian=True, only the position service fires."""
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
        is_venetian=False,
        tilt=80,  # Set but ignored because is_venetian=False
    )

    with (
        _patch_caps_dual_axis(),
        patch.object(
            svc, "_wait_for_position_settle", new=AsyncMock(return_value=(True, 60))
        ),
    ):
        outcome, _ = await svc.apply_position(entity_id, 60, "solar", ctx)

    assert outcome == "sent"
    assert hass.services.async_call.call_count == 1
    assert hass.services.async_call.call_args_list[0].args[1] == "set_cover_position"


@pytest.mark.asyncio
async def test_settle_helper_returns_when_target_reached(svc, hass) -> None:
    """The settle poll returns True as soon as current_position is within tolerance."""
    entity_id = "cover.venetian"
    samples = iter([_state_with_position(80), _state_with_position(50)])
    hass.states.get.side_effect = lambda _eid: next(samples)

    with patch(
        "custom_components.adaptive_cover_pro.managers.cover_command.check_cover_features",
        return_value={
            "has_set_position": True,
            "has_set_tilt_position": True,
            "has_open": True,
            "has_close": True,
            "has_stop": True,
        },
    ):
        reached, last = await svc._wait_for_position_settle(entity_id, target=50)

    assert reached is True
    assert last == 50


@pytest.mark.asyncio
async def test_settle_helper_returns_on_unavailable_position(svc, hass) -> None:
    """If current_position drops to None, settle bails out instead of looping."""
    entity_id = "cover.flaky"
    state = MagicMock()
    state.state = "unknown"
    state.attributes = {}
    hass.states.get.return_value = state

    reached, last = await svc._wait_for_position_settle(entity_id, target=50)

    assert reached is False
    assert last is None

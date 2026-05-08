"""Unit tests for VenetianPolicy — cover-type policy behaviour.

Covers the retract-threshold guard in ``after_position_command`` (issue #33
Defect B: tilt command fired for fully-retracted covers).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import SERVICE_SET_COVER_POSITION

from custom_components.adaptive_cover_pro.const import (
    CONF_VENETIAN_TILT_SKIP_ABOVE,
    DEFAULT_VENETIAN_TILT_SKIP_ABOVE,
)
from custom_components.adaptive_cover_pro.cover_types.venetian import VenetianPolicy
from custom_components.adaptive_cover_pro.managers.cover_command import PositionContext


def test_retract_threshold_constants_exist() -> None:
    """CONF and DEFAULT constants for the retract threshold must be exported."""
    assert CONF_VENETIAN_TILT_SKIP_ABOVE == "venetian_tilt_skip_above"
    assert DEFAULT_VENETIAN_TILT_SKIP_ABOVE == 95


def _make_policy(*, tilt_skip_above: int = 95) -> VenetianPolicy:
    """Return a VenetianPolicy with a fully mocked sequencer."""
    policy = VenetianPolicy()
    mock_seq = MagicMock()
    mock_seq.run_sequence = AsyncMock()
    mock_seq.stamp_position_command = MagicMock()
    policy._sequencer = mock_seq
    policy._tilt_skip_above = tilt_skip_above
    return policy


def _ctx(policy: VenetianPolicy, *, tilt: int = 80) -> PositionContext:
    return PositionContext(
        auto_control=True,
        manual_override=False,
        sun_just_appeared=False,
        min_change=1,
        time_threshold=0,
        special_positions=[0, 100],
        force=True,
        tilt=tilt,
        policy=policy,
    )


@pytest.mark.asyncio
async def test_after_position_command_skips_run_sequence_when_position_above_threshold() -> (
    None
):
    """When position > tilt_skip_above, neither stamp nor run_sequence fires."""
    policy = _make_policy(tilt_skip_above=95)

    await policy.after_position_command(
        cmd_svc=MagicMock(),
        entity_id="cover.venetian_x",
        service=SERVICE_SET_COVER_POSITION,
        position=98,
        context=_ctx(policy),
        reason="solar",
    )

    policy._sequencer.stamp_position_command.assert_not_called()
    policy._sequencer.run_sequence.assert_not_awaited()


@pytest.mark.asyncio
async def test_after_position_command_skips_at_100_percent() -> None:
    """Fully retracted (position=100) must also skip the tilt command."""
    policy = _make_policy(tilt_skip_above=95)

    await policy.after_position_command(
        cmd_svc=MagicMock(),
        entity_id="cover.venetian_x",
        service=SERVICE_SET_COVER_POSITION,
        position=100,
        context=_ctx(policy),
        reason="solar",
    )

    policy._sequencer.stamp_position_command.assert_not_called()
    policy._sequencer.run_sequence.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("position", [95, 60, 0])
async def test_after_position_command_runs_sequence_at_or_below_threshold(
    position: int,
) -> None:
    """When position <= tilt_skip_above, the full sequence fires."""
    policy = _make_policy(tilt_skip_above=95)

    await policy.after_position_command(
        cmd_svc=MagicMock(),
        entity_id="cover.venetian_x",
        service=SERVICE_SET_COVER_POSITION,
        position=position,
        context=_ctx(policy),
        reason="solar",
    )

    policy._sequencer.stamp_position_command.assert_called_once_with("cover.venetian_x")
    policy._sequencer.run_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_after_position_command_respects_custom_threshold() -> None:
    """Threshold is read from the policy instance, not a module-level constant."""
    policy = _make_policy(tilt_skip_above=80)

    await policy.after_position_command(
        cmd_svc=MagicMock(),
        entity_id="cover.venetian_x",
        service=SERVICE_SET_COVER_POSITION,
        position=81,
        context=_ctx(policy),
        reason="solar",
    )

    policy._sequencer.stamp_position_command.assert_not_called()
    policy._sequencer.run_sequence.assert_not_awaited()

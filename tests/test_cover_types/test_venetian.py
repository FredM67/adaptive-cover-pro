"""Unit tests for VenetianPolicy — cover-type policy behaviour.

Covers the retract-threshold guard in ``after_position_command`` (issue #33).
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


def test_geometry_schema_accepts_venetian_mode() -> None:
    """GEOMETRY_VENETIAN_SCHEMA validates both allowed mode values."""
    from custom_components.adaptive_cover_pro.const import (
        CONF_VENETIAN_MODE,
        DEFAULT_VENETIAN_MODE,
        VENETIAN_MODE_TILT_ONLY,
    )
    from custom_components.adaptive_cover_pro.cover_types.venetian import (
        GEOMETRY_VENETIAN_SCHEMA,
    )

    result_default = GEOMETRY_VENETIAN_SCHEMA({})
    assert result_default[CONF_VENETIAN_MODE] == DEFAULT_VENETIAN_MODE

    result_tilt_only = GEOMETRY_VENETIAN_SCHEMA(
        {CONF_VENETIAN_MODE: VENETIAN_MODE_TILT_ONLY}
    )
    assert result_tilt_only[CONF_VENETIAN_MODE] == VENETIAN_MODE_TILT_ONLY


def test_venetian_mode_constants_exist() -> None:
    """Mode constants must exist in const.py with the documented values."""
    from custom_components.adaptive_cover_pro.const import (
        CONF_VENETIAN_MODE,
        DEFAULT_VENETIAN_MODE,
        VENETIAN_MODE_POSITION_AND_TILT,
        VENETIAN_MODE_TILT_ONLY,
        VENETIAN_MODES,
    )

    assert CONF_VENETIAN_MODE == "venetian_mode"
    assert VENETIAN_MODE_POSITION_AND_TILT == "position_and_tilt"
    assert VENETIAN_MODE_TILT_ONLY == "tilt_only"
    assert DEFAULT_VENETIAN_MODE == VENETIAN_MODE_POSITION_AND_TILT
    assert VENETIAN_MODES == (VENETIAN_MODE_POSITION_AND_TILT, VENETIAN_MODE_TILT_ONLY)


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
@pytest.mark.parametrize("position", [95, 60, 6])
async def test_after_position_command_runs_sequence_at_or_below_threshold(
    position: int,
) -> None:
    """When position is between the lower and upper thresholds, the full sequence fires."""
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
class TestVenetianMaybeUpdateTiltOnly:
    """maybe_update_tilt_only drives continuous tilt when position hasn't changed."""

    def _policy_with_last_tilt(
        self,
        *,
        tilt_value: int | None,
        suppression: bool = False,
    ) -> VenetianPolicy:
        from custom_components.adaptive_cover_pro.const import VENETIAN_MODE_TILT_ONLY

        policy = _make_policy()
        policy._venetian_mode = VENETIAN_MODE_TILT_ONLY
        policy._last_tilt = tilt_value
        mock_seq = MagicMock()
        mock_seq.update_tilt_only = AsyncMock()
        mock_seq.is_in_suppression = MagicMock(return_value=suppression)
        policy._sequencer = mock_seq
        return policy

    async def test_emits_when_last_tilt_set_and_no_suppression(self):
        policy = self._policy_with_last_tilt(tilt_value=70)
        await policy.maybe_update_tilt_only(
            "cover.x", current_position=0, context=MagicMock(), reason="solar"
        )
        policy._sequencer.update_tilt_only.assert_awaited_once()

    async def test_skips_when_no_last_tilt(self):
        policy = self._policy_with_last_tilt(tilt_value=None)
        await policy.maybe_update_tilt_only(
            "cover.x", current_position=0, context=MagicMock(), reason="solar"
        )
        policy._sequencer.update_tilt_only.assert_not_awaited()

    async def test_skips_when_suppression_window_open(self):
        policy = self._policy_with_last_tilt(tilt_value=70, suppression=True)
        await policy.maybe_update_tilt_only(
            "cover.x", current_position=0, context=MagicMock(), reason="solar"
        )
        policy._sequencer.update_tilt_only.assert_not_awaited()

    async def test_skips_when_no_sequencer(self):
        policy = _make_policy()
        policy._last_tilt = 70
        policy._sequencer = None
        await policy.maybe_update_tilt_only(
            "cover.x", current_position=0, context=MagicMock(), reason="solar"
        )


@pytest.mark.asyncio
async def test_after_position_command_fires_tilt_at_position_zero() -> None:
    """At position=0 the sequence MUST fire — issue #33 regression.

    The removed tilt_skip_below option silently blocked tilt at fully-closed
    positions. Default behavior must now allow tilt at position=0.
    """
    policy = _make_policy()

    await policy.after_position_command(
        cmd_svc=MagicMock(),
        entity_id="cover.venetian_x",
        service=SERVICE_SET_COVER_POSITION,
        position=0,
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

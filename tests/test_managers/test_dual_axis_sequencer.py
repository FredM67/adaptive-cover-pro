"""Unit tests for ``DualAxisSequencer``.

The sequencer owns:
- the venetian tilt-axis suppression window (``stamp_position_command`` /
  ``is_in_suppression``), and
- the post-position settle loop + ``set_cover_tilt_position`` call
  (``run_sequence``).

These tests exercise it in isolation — the integration with
``CoverCommandService.apply_position`` is covered in
``tests/test_cover_command_venetian.py``.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.adaptive_cover_pro.const import (
    VENETIAN_TILT_SUPPRESSION_SECONDS,
)
from custom_components.adaptive_cover_pro.managers.dual_axis_sequencer import (
    DualAxisSequencer,
)


def _build_sequencer(
    *, current_positions=None, dry_run=False, set_commanded_position=None
):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    if current_positions is None:
        current_positions = []
    iter_positions = iter(current_positions)
    if set_commanded_position is None:
        set_commanded_position = lambda *_: None  # noqa: E731
    return (
        hass,
        DualAxisSequencer(
            hass=hass,
            logger=MagicMock(),
            grace_mgr=MagicMock(),
            get_current_position=lambda _eid: next(iter_positions, None),
            set_commanded_position=set_commanded_position,
            position_tolerance=5,
            is_dry_run=lambda: dry_run,
        ),
    )


@pytest.mark.unit
class TestSuppressionWindow:
    """``stamp_position_command`` and ``is_in_suppression`` mediate the back-rotate window."""

    def test_no_stamp_means_not_suppressed(self):
        _, seq = _build_sequencer()
        assert seq.is_in_suppression("cover.x") is False

    def test_fresh_stamp_is_suppressed(self):
        _, seq = _build_sequencer()
        seq.stamp_position_command("cover.x")
        assert seq.is_in_suppression("cover.x") is True

    def test_stale_stamp_expires(self):
        _, seq = _build_sequencer()
        seq._suppression_at["cover.x"] = dt.datetime.now(dt.UTC) - dt.timedelta(
            seconds=VENETIAN_TILT_SUPPRESSION_SECONDS + 1
        )
        assert seq.is_in_suppression("cover.x") is False


@pytest.mark.asyncio
class TestSettleAndTilt:
    """Settle-loop and tilt-service-call branches of ``run_sequence``."""

    async def test_settle_returns_when_target_reached(self):
        # Sequence: 80 (off-target), 50 (within 5%-tolerance) → reached.
        _, seq = _build_sequencer(current_positions=[80, 50])
        reached, last = await seq._wait_for_position_settle("cover.x", target=50)
        assert reached is True
        assert last == 50

    async def test_settle_bails_on_unavailable(self):
        _, seq = _build_sequencer(current_positions=[None])
        reached, last = await seq._wait_for_position_settle("cover.x", target=50)
        assert reached is False
        assert last is None

    async def test_run_sequence_emits_tilt_after_settle(self):
        hass, seq = _build_sequencer(current_positions=[60])
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 60))
        await seq.run_sequence(
            "cover.x", position_target=60, tilt_target=80, reason="solar"
        )
        assert hass.services.async_call.call_count == 1
        called = hass.services.async_call.call_args.args
        assert called[1] == "set_cover_tilt_position"
        assert called[2]["tilt_position"] == 80

    async def test_run_sequence_records_last_tilt_target(self):
        _, seq = _build_sequencer()
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 60))
        await seq.run_sequence(
            "cover.x", position_target=60, tilt_target=80, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") == 80

    async def test_dry_run_skips_service_call(self):
        hass, seq = _build_sequencer(dry_run=True)
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 60))
        await seq.run_sequence(
            "cover.x", position_target=60, tilt_target=80, reason="solar"
        )
        assert hass.services.async_call.call_count == 0


@pytest.mark.asyncio
class TestPostTiltRebase:
    """After a successful tilt command, the commanded position is rebased to the
    actual post-tilt position so reconciliation sees zero drift.
    """

    async def test_rebases_commanded_position_to_actual_post_tilt(self):
        """After tilt, set_commanded_position is called with the actual position."""
        set_cmd_pos = MagicMock()
        # position_target=50, post-tilt actual=56 → |delta|=6 > tolerance(5).
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        seq._get_current_position = lambda _eid: 56
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_called_once_with("cover.x", 56)

    async def test_does_not_rebase_when_post_tilt_position_none(self):
        """If current_position is unavailable after tilt, skip the rebase."""
        set_cmd_pos = MagicMock()
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        seq._get_current_position = lambda _eid: None
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_not_called()

    async def test_does_not_rebase_when_drift_within_tolerance(self):
        """Drift of 2% (≤ tolerance of 5%) should not trigger a rebase."""
        set_cmd_pos = MagicMock()
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        # position_target=50, actual=52 → |delta|=2 ≤ 5
        seq._get_current_position = lambda _eid: 52
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_not_called()

    async def test_does_not_rebase_when_tilt_service_fails(self):
        """If the tilt service call raises, rebase must not run."""
        from homeassistant.exceptions import HomeAssistantError

        set_cmd_pos = MagicMock()
        hass, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("tilt fail")
        )
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_not_called()

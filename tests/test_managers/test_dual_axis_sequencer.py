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


def _build_sequencer(*, current_positions=None, dry_run=False):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    if current_positions is None:
        current_positions = []
    iter_positions = iter(current_positions)
    return (
        hass,
        DualAxisSequencer(
            hass=hass,
            logger=MagicMock(),
            grace_mgr=MagicMock(),
            get_current_position=lambda _eid: next(iter_positions, None),
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

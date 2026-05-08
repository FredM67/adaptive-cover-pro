"""Dual-axis cover-command sequencer for venetian blinds.

Real-motor venetian blinds (KNX, Somfy IO, Shelly 2PM) back-rotate the
slats while moving vertically: firing ``set_cover_position`` and
``set_cover_tilt_position`` simultaneously leaves tilt drifting. The
sequencer runs the position command first, polls ``current_position``
until the cover settles (or a timeout / no-progress sample budget fires),
then sends the tilt command — overriding the motor back-rotate exactly
once, after vertical motion has finished.

Owned by ``VenetianPolicy``; constructed when the policy is attached to
the coordinator. Other cover-type policies have no sequencer at all.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.components.cover.const import DOMAIN as COVER_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_SET_COVER_TILT_POSITION,
)
from homeassistant.exceptions import HomeAssistantError

from ..const import (
    ATTR_TILT_POSITION,
    VENETIAN_POSITION_SETTLE_NO_CHANGE_SAMPLES,
    VENETIAN_POSITION_SETTLE_POLL_SECONDS,
    VENETIAN_POSITION_SETTLE_TIMEOUT_SECONDS,
    VENETIAN_POST_TILT_REBASE_DELAY_SECONDS,
    VENETIAN_TILT_SUPPRESSION_SECONDS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class DualAxisSequencer:
    """Position→settle→tilt sequencer + tilt-axis suppression window."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        logger,
        grace_mgr,
        get_current_position: Callable[[str], int | None],
        set_commanded_position: Callable[[str, int], None],
        position_tolerance: int,
        is_dry_run: Callable[[], bool],
    ) -> None:
        """Bind HA + cmd_svc dependencies; per-entity timestamps start empty."""
        self._hass = hass
        self._logger = logger
        self._grace_mgr = grace_mgr
        self._get_current_position = get_current_position
        self._set_commanded_position = set_commanded_position
        self._position_tolerance = position_tolerance
        self._is_dry_run = is_dry_run
        # Per-entity timestamps. Keep these in the sequencer (rather than on
        # CoverCommandService.PerEntityState) so non-venetian covers carry no
        # dual-axis state at all.
        self._suppression_at: dict[str, dt.datetime] = {}
        self._tilt_targets: dict[str, int] = {}
        self._tilt_sent_at: dict[str, dt.datetime] = {}

    # -- suppression window ------------------------------------------------ #

    def stamp_position_command(self, entity_id: str) -> None:
        """Record that a ``set_cover_position`` was just emitted."""
        self._suppression_at[entity_id] = dt.datetime.now(dt.UTC)

    def is_in_suppression(self, entity_id: str) -> bool:
        """Return whether the back-rotate window is still open for this cover."""
        ts = self._suppression_at.get(entity_id)
        if ts is None:
            return False
        elapsed = (dt.datetime.now(dt.UTC) - ts).total_seconds()
        return elapsed < VENETIAN_TILT_SUPPRESSION_SECONDS

    # -- tilt sequence ----------------------------------------------------- #

    def last_tilt_target(self, entity_id: str) -> int | None:
        """Return the last tilt target sent (for diagnostics / tests)."""
        return self._tilt_targets.get(entity_id)

    async def run_sequence(
        self,
        entity_id: str,
        *,
        position_target: int,
        tilt_target: int,
        reason: str,
    ) -> None:
        """Wait for vertical motion to settle, then send the tilt command."""
        await self._wait_for_position_settle(entity_id, position_target)

        if self._is_dry_run():
            self._logger.info(
                "[dry_run] would send cover.set_cover_tilt_position %s → %s%%",
                entity_id,
                tilt_target,
            )
            return

        self._tilt_targets[entity_id] = tilt_target
        self._tilt_sent_at[entity_id] = dt.datetime.now(dt.UTC)
        # Restart the grace window so the tilt-axis change isn't read as a
        # user touch by manual_override detection.
        self._grace_mgr.start_command_grace_period(entity_id)

        self._logger.info(
            "[%s] Tilt %s → %s%% (paired with position %s%%)",
            reason,
            entity_id,
            tilt_target,
            position_target,
        )

        try:
            await self._hass.services.async_call(
                COVER_DOMAIN,
                SERVICE_SET_COVER_TILT_POSITION,
                {ATTR_ENTITY_ID: entity_id, ATTR_TILT_POSITION: tilt_target},
            )
        except HomeAssistantError as err:
            self._logger.warning(
                "Service call %s.%s failed for %s: %s",
                COVER_DOMAIN,
                SERVICE_SET_COVER_TILT_POSITION,
                entity_id,
                err,
            )
            return

        # Wait for the motor's mechanical back-drive on the vertical axis to
        # settle before reading current_position for the rebase. Without this
        # delay the read races the asynchronous back-drive and captures the
        # pre-settle value, causing the rebase to see zero drift and skip.
        await asyncio.sleep(VENETIAN_POST_TILT_REBASE_DELAY_SECONDS)

        self._rebase_commanded_position(entity_id, position_target)

    def _rebase_commanded_position(self, entity_id: str, position_target: int) -> None:
        """Reset the cmd_svc target to the actual post-tilt position.

        After set_cover_tilt_position returns, the motor has finished its
        mechanical back-drive of the vertical axis. Reading current_position now
        and pushing that value into set_commanded_position() makes the next
        reconciliation pass compute zero delta — closing the loop where
        reconciliation re-issued set_cover_position, which re-fired the
        sequencer, which back-drove the cover again.
        """
        actual = self._get_current_position(entity_id)
        if actual is None:
            return
        if abs(actual - position_target) <= self._position_tolerance:
            return
        self._logger.debug(
            "Venetian post-tilt rebase: %s commanded %s%% → actual %s%% "
            "(absorbing motor back-drive)",
            entity_id,
            position_target,
            actual,
        )
        self._set_commanded_position(entity_id, actual)

    async def _wait_for_position_settle(
        self, entity_id: str, target: int
    ) -> tuple[bool, int | None]:
        """Poll ``current_position`` until settle, no-progress, or timeout."""
        deadline = dt.datetime.now(dt.UTC) + dt.timedelta(
            seconds=VENETIAN_POSITION_SETTLE_TIMEOUT_SECONDS
        )
        last_position: int | None = None
        unchanged_samples = 0

        while dt.datetime.now(dt.UTC) < deadline:
            current = self._get_current_position(entity_id)
            if current is None:
                return False, last_position

            if abs(current - target) <= self._position_tolerance:
                return True, current

            if last_position is not None and current == last_position:
                unchanged_samples += 1
                if unchanged_samples >= VENETIAN_POSITION_SETTLE_NO_CHANGE_SAMPLES:
                    self._logger.debug(
                        "Venetian settle: %s stalled at %s%% (target %s%%) "
                        "after %d unchanged samples",
                        entity_id,
                        current,
                        target,
                        unchanged_samples,
                    )
                    return False, current
            else:
                unchanged_samples = 0

            last_position = current
            await asyncio.sleep(VENETIAN_POSITION_SETTLE_POLL_SECONDS)

        self._logger.debug(
            "Venetian settle: %s timed out at %s%% (target %s%%) after %.0fs",
            entity_id,
            last_position,
            target,
            VENETIAN_POSITION_SETTLE_TIMEOUT_SECONDS,
        )
        return False, last_position

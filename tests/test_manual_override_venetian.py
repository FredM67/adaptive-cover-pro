"""Tilt-axis manual-override tests for the cover_venetian sensor type.

Issue #33: real-motor venetians (KNX, Somfy IO, Shelly 2PM) back-rotate the
slats while moving vertically. AdaptiveCoverManager must therefore ignore
tilt-axis drift inside the venetian tilt-suppression window, but still flag
genuine "user grabbed the wand" tilt deltas outside that window. Position-
axis drift continues to behave exactly as it does for any other cover type.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

from custom_components.adaptive_cover_pro.managers.manual_override import (
    AdaptiveCoverManager,
)


def _make_event(entity_id: str, *, position: int | None, tilt: int | None):
    """Build a fake StateChangedData reporting both axes."""
    attrs: dict = {}
    if position is not None:
        attrs["current_position"] = position
    if tilt is not None:
        attrs["current_tilt_position"] = tilt
    event = MagicMock()
    event.entity_id = entity_id
    event.new_state = MagicMock()
    event.new_state.state = "stopped"
    event.new_state.attributes = attrs
    event.new_state.last_updated = dt.datetime.now(dt.UTC)
    return event


def _make_manager(entity_id: str) -> AdaptiveCoverManager:
    mgr = AdaptiveCoverManager(
        hass=MagicMock(),
        reset_duration={"hours": 2},
        logger=MagicMock(),
    )
    mgr.add_covers([entity_id])
    return mgr


def test_tilt_drift_inside_suppression_window_is_ignored() -> None:
    """Tilt drift right after a position command is the motor back-rotate.

    The user's complaint in #33 is that this drift was being read as
    manual_override on the paired tilt instance.  With dual-axis venetian,
    `is_in_tilt_suppression` returns True during the window and the manager
    must NOT mark the cover as manual.
    """
    entity_id = "cover.venetian_kitchen"
    mgr = _make_manager(entity_id)

    mgr.handle_state_change(
        states_data=_make_event(entity_id, position=50, tilt=20),
        our_state=50,
        blind_type="cover_venetian",
        allow_reset=True,
        is_waiting=lambda _eid: False,
        manual_threshold=5,
        our_tilt=70,
        is_in_tilt_suppression=lambda _eid: True,
    )

    assert not mgr.is_cover_manual(entity_id)


def test_tilt_drift_outside_suppression_trips_override() -> None:
    """Once the suppression window has elapsed, tilt drift is a user touch."""
    entity_id = "cover.venetian_office"
    mgr = _make_manager(entity_id)

    mgr.handle_state_change(
        states_data=_make_event(entity_id, position=50, tilt=20),
        our_state=50,
        blind_type="cover_venetian",
        allow_reset=True,
        is_waiting=lambda _eid: False,
        manual_threshold=5,
        our_tilt=70,
        is_in_tilt_suppression=lambda _eid: False,
    )

    assert mgr.is_cover_manual(entity_id)


def test_tilt_drift_within_threshold_is_ignored_even_outside_window() -> None:
    """Tilt deltas under the threshold floor are ignored regardless of suppression."""
    entity_id = "cover.venetian_lounge"
    mgr = _make_manager(entity_id)

    mgr.handle_state_change(
        states_data=_make_event(entity_id, position=50, tilt=72),
        our_state=50,
        blind_type="cover_venetian",
        allow_reset=True,
        is_waiting=lambda _eid: False,
        manual_threshold=5,
        our_tilt=70,
        is_in_tilt_suppression=lambda _eid: False,
    )

    assert not mgr.is_cover_manual(entity_id)


def test_position_drift_ignores_tilt_suppression() -> None:
    """Position-axis drift always evaluates regardless of tilt-suppression state.

    Suppression covers ONLY the tilt-axis side-effect. A user who moves the
    cover vertically still triggers position-axis manual override.
    """
    entity_id = "cover.venetian_master"
    mgr = _make_manager(entity_id)
    # check_cover_features falls back to defaults when caps are missing
    mgr.hass.states.get = MagicMock(return_value=None)

    mgr.handle_state_change(
        states_data=_make_event(entity_id, position=80, tilt=70),
        our_state=50,
        blind_type="cover_venetian",
        allow_reset=True,
        is_waiting=lambda _eid: False,
        manual_threshold=5,
        our_tilt=70,
        is_in_tilt_suppression=lambda _eid: True,
    )

    assert mgr.is_cover_manual(entity_id)


def test_non_venetian_cover_ignores_tilt_axis_inputs() -> None:
    """A blind cover passing our_tilt by mistake must not change behavior."""
    entity_id = "cover.blind"
    mgr = _make_manager(entity_id)
    mgr.hass.states.get = MagicMock(return_value=None)

    mgr.handle_state_change(
        states_data=_make_event(entity_id, position=50, tilt=10),
        our_state=50,
        blind_type="cover_blind",
        allow_reset=True,
        is_waiting=lambda _eid: False,
        manual_threshold=5,
        our_tilt=70,  # ignored — blind type
        is_in_tilt_suppression=lambda _eid: False,
    )

    assert not mgr.is_cover_manual(entity_id)

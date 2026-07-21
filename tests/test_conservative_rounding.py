"""Tests for directional (conservative) position rounding (issue #978).

Conservative rounding biases the solar position toward full coverage instead of
nearest integer:
  - Blind / tilt / venetian  (0% = closed = full coverage): floor()
  - Awning                   (100% = extended = full coverage): ceil()

This is now always-on behavior (no opt-in flag) keyed off the policy's
``open_blocks_sun`` axis attribute.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from custom_components.adaptive_cover_pro.pipeline.helpers import (
    compute_solar_position,
    solar_position_from_geometry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config():
    return SimpleNamespace(
        min_pos=None,
        max_pos=None,
        min_pos_sun_only=False,
        max_pos_sun_only=False,
        min_pos_sun_tracking=None,
    )


def _policy(*, open_blocks_sun: bool):
    return SimpleNamespace(axes=[SimpleNamespace(open_blocks_sun=open_blocks_sun)])


def _snapshot(
    *,
    calc_pct: float,
    open_blocks_sun: bool = False,
    floor_active: bool = False,
):
    """Build a minimal PipelineSnapshot-like namespace for solar branch tests.

    ``floor_active`` defaults to *False* so the 1%-floor doesn't mask rounding
    differences for values near zero.  Tests that specifically exercise the
    floor behaviour can opt in.
    """
    return SimpleNamespace(
        cover=SimpleNamespace(
            direct_sun_valid=True,
            calculate_percentage=lambda: int(round(calc_pct)),
            calculate_raw_percentage=lambda: calc_pct,
        ),
        config=_config(),
        policy=_policy(open_blocks_sun=open_blocks_sun),
        minimize_movements=False,
        max_coverage_steps=1,
        solar_floor_active=floor_active,
    )


# ---------------------------------------------------------------------------
# Blind direction (open_blocks_sun=False, full_coverage_at_zero=True)
# floor() toward 0 = more closed = more coverage
# ---------------------------------------------------------------------------


class TestBlindRounding:
    """Blinds always round DOWN (floor) toward closed."""

    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (45.6, 45),  # round() would give 46; floor gives 45 (more closed)
            (45.4, 45),  # round() also gives 45; floor agrees
            (10.9, 10),  # round() would give 11; floor gives 10
            (99.9, 99),  # round() would give 100; floor gives 99 (still covered)
            (0.9, 0),  # floor → 0; solar floor clamp NOT active → stays 0
        ],
    )
    def test_floor_rounds_toward_closed(self, pct, expected):
        snap = _snapshot(calc_pct=pct, open_blocks_sun=False)
        assert compute_solar_position(snap) == expected

    @pytest.mark.parametrize("pct", [0.0, 10.0, 45.0, 67.0, 100.0])
    def test_integer_values_unchanged(self, pct):
        """floor(n.0) == round(n.0) — no extra movement on clean integers."""
        snap = _snapshot(calc_pct=pct, open_blocks_sun=False)
        assert compute_solar_position(snap) == int(pct)

    def test_floor_never_more_open_than_round(self):
        """floor(x) <= round(x) for blinds — directional rounding is never more open."""
        pct = 45.7  # round→46, floor→45
        snap = _snapshot(calc_pct=pct, open_blocks_sun=False)
        assert compute_solar_position(snap) <= int(round(pct))


# ---------------------------------------------------------------------------
# Awning direction (open_blocks_sun=True, full_coverage_at_zero=False)
# ceil() toward 100 = more extended = more coverage
# ---------------------------------------------------------------------------


class TestAwningRounding:
    """Awnings always round UP (ceil) toward extended."""

    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (45.1, 46),  # round() would give 45; ceil gives 46 (more extended)
            (45.6, 46),  # round() also gives 46; ceil agrees
            (10.1, 11),  # round() would give 10; ceil gives 11
            (0.1, 1),  # round() would give 0; ceil gives 1
            (99.0, 99),  # already integer — no change
        ],
    )
    def test_ceil_rounds_toward_extended(self, pct, expected):
        snap = _snapshot(calc_pct=pct, open_blocks_sun=True)
        assert compute_solar_position(snap) == expected

    @pytest.mark.parametrize("pct", [0.0, 10.0, 45.0, 67.0, 100.0])
    def test_integer_values_unchanged(self, pct):
        """ceil(n.0) == round(n.0) — no extra movement on clean integers."""
        snap = _snapshot(calc_pct=pct, open_blocks_sun=True)
        assert compute_solar_position(snap) == int(pct)

    def test_ceil_never_less_extended_than_round(self):
        """ceil(x) >= round(x) for awnings — directional rounding is never less extended."""
        pct = 45.3  # round→45, ceil→46
        snap = _snapshot(calc_pct=pct, open_blocks_sun=True)
        assert compute_solar_position(snap) >= int(round(pct))


# ---------------------------------------------------------------------------
# solar_position_from_geometry primitive — direct unit tests
# ---------------------------------------------------------------------------


class TestSolarPositionFromGeometryPrimitive:
    """Test the lower-level primitive that compute_solar_position delegates to."""

    def _cover(self, pct: float):
        return SimpleNamespace(
            calculate_percentage=lambda: int(round(pct)),
            calculate_raw_percentage=lambda: pct,
        )

    def test_blind_floor(self):
        cover = self._cover(67.9)
        policy = _policy(open_blocks_sun=False)
        result = solar_position_from_geometry(
            cover,
            _config(),
            minimize_movements=False,
            max_coverage_steps=1,
            policy=policy,
            floor_active=False,
        )
        assert result == math.floor(67.9)

    def test_awning_ceil(self):
        cover = self._cover(67.1)
        policy = _policy(open_blocks_sun=True)
        result = solar_position_from_geometry(
            cover,
            _config(),
            minimize_movements=False,
            max_coverage_steps=1,
            policy=policy,
            floor_active=False,
        )
        assert result == math.ceil(67.1)

    def test_no_policy_falls_back_to_round(self):
        """When policy is None, falls back to round() without crashing."""
        cover = self._cover(67.7)
        result = solar_position_from_geometry(
            cover,
            _config(),
            minimize_movements=False,
            max_coverage_steps=1,
            policy=None,
            floor_active=False,
        )
        assert result == int(round(67.7))

    @pytest.mark.parametrize("pct", [10.0, 33.0, 67.0, 100.0])
    def test_integer_pct_same_as_round(self, pct):
        """floor/ceil of an integer == round of that integer."""
        cover = self._cover(pct)
        policy = _policy(open_blocks_sun=False)
        result = solar_position_from_geometry(
            cover,
            _config(),
            minimize_movements=False,
            max_coverage_steps=1,
            policy=policy,
            floor_active=False,
        )
        assert result == int(round(pct))

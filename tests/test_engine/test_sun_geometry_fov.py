"""Tests for the ``fov_from_reveal`` derivation helper (issue #565).

The Measurements FOV mode derives a symmetric half-angle from the window
opening width and the reveal (recess) depth in front of the cover. The helper
is the single source of that arctan — both the config-flow save path and the
summary display call it.
"""

import pytest

from custom_components.adaptive_cover_pro.const import (
    CONF_FOV_LEFT,
    DEFAULT_FOV_LEFT,
    OPTION_RANGES,
)
from custom_components.adaptive_cover_pro.engine.sun_geometry import fov_from_reveal


def test_width_2_depth_1_is_45_degrees():
    # atan((2/2)/1) = atan(1) = 45°
    assert fov_from_reveal(2.0, 1.0) == 45


def test_width_2_depth_half_is_63_degrees():
    # atan((2/2)/0.5) = atan(2) ≈ 63.43° → rounds to 63
    assert fov_from_reveal(2.0, 0.5) == 63


def test_zero_depth_is_full_hemisphere_default():
    assert fov_from_reveal(2.0, 0.0) == DEFAULT_FOV_LEFT
    assert fov_from_reveal(2.0, 0.0) == 90


def test_zero_width_is_full_hemisphere_default():
    assert fov_from_reveal(0.0, 1.0) == DEFAULT_FOV_LEFT


def test_negative_inputs_fall_back_to_default():
    assert fov_from_reveal(-1.0, 1.0) == DEFAULT_FOV_LEFT
    assert fov_from_reveal(2.0, -1.0) == DEFAULT_FOV_LEFT


def test_result_clamped_to_fov_range():
    lo, hi = OPTION_RANGES[CONF_FOV_LEFT]
    # Very wide, very shallow → angle approaches 90, never exceeds the range.
    assert fov_from_reveal(50.0, 0.01) <= hi
    assert fov_from_reveal(50.0, 0.01) >= lo


def test_returns_int():
    assert isinstance(fov_from_reveal(1.2, 0.5), int)


@pytest.mark.parametrize(
    ("width", "depth", "expected"),
    [
        (1.0, 1.0, 27),  # atan(0.5) ≈ 26.57 → 27
        (3.0, 1.0, 56),  # atan(1.5) ≈ 56.31 → 56
        (1.2, 0.5, 50),  # atan(1.2) ≈ 50.19 → 50 (the summary example)
    ],
)
def test_known_angles(width, depth, expected):
    assert fov_from_reveal(width, depth) == expected

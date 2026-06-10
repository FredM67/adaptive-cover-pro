"""Tests for the FOV-mode selector vocabulary and field registration (#565).

The two-mode FOV selector adds a ``CONF_FOV_MODE`` option and a ``FovMode``
StrEnum. ANGLES is the default (today's fov_left/right sliders); MEASUREMENTS
derives the FOV from the window width + reveal depth. No new measurement fields.
"""

from __future__ import annotations

from custom_components.adaptive_cover_pro import config_fields as cf
from custom_components.adaptive_cover_pro.const import CONF_FOV_MODE, FovMode


def test_fov_mode_enum_values():
    assert FovMode.ANGLES == "angles"
    assert FovMode.MEASUREMENTS == "measurements"


def test_conf_fov_mode_key():
    assert CONF_FOV_MODE == "fov_mode"


def test_fov_mode_default_is_angles():
    assert FovMode.ANGLES.value == cf.option_default(CONF_FOV_MODE)


def test_fov_mode_field_spec_registered_as_select():
    spec = cf.FIELD_SPECS[CONF_FOV_MODE]
    assert spec.validator is cf.ValidatorKind.SELECT
    assert spec.select_options == tuple(m.value for m in FovMode)


def test_fov_mode_in_sun_tracking_section():
    spec = cf.FIELD_SPECS[CONF_FOV_MODE]
    assert spec.section == cf.SECTION_SUN_TRACKING


def test_fov_mode_is_a_valid_blind_option_key():
    # The options-service rejects keys not in live_option_keys, so the blind
    # policy must advertise CONF_FOV_MODE for saves to be accepted.
    from custom_components.adaptive_cover_pro.const import CoverType
    from custom_components.adaptive_cover_pro.cover_types import get_policy

    assert CONF_FOV_MODE in get_policy(CoverType.BLIND).live_option_keys()


def test_fov_mode_not_a_valid_awning_option_key():
    from custom_components.adaptive_cover_pro.const import CoverType
    from custom_components.adaptive_cover_pro.cover_types import get_policy

    assert CONF_FOV_MODE not in get_policy(CoverType.AWNING).live_option_keys()

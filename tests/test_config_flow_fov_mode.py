"""Config-flow behaviour for the two-mode FOV selector (#565).

Covers per-mode schema rendering, the re-render-on-mode-change pattern, the
save path that derives fov_left/right in MEASUREMENTS mode, and backward
compatibility when ``fov_mode`` is absent.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.adaptive_cover_pro.config_flow import (
    OptionsFlowHandler,
    _get_sun_tracking_schema,
)
from custom_components.adaptive_cover_pro.const import (
    CONF_FOV_LEFT,
    CONF_FOV_MODE,
    CONF_FOV_RIGHT,
    CONF_WINDOW_DEPTH,
    CONF_WINDOW_WIDTH,
    FovMode,
)
from custom_components.adaptive_cover_pro.const import CoverType


def _keys(schema) -> set[str]:
    return {str(m) for m in schema.schema}


# ----------------------------------------------------------------------------
# Per-mode schema rendering
# ----------------------------------------------------------------------------


def test_blind_angles_mode_shows_fov_sliders():
    schema = _get_sun_tracking_schema(CoverType.BLIND, mode=FovMode.ANGLES)
    keys = _keys(schema)
    assert CONF_FOV_LEFT in keys
    assert CONF_FOV_RIGHT in keys
    assert CONF_FOV_MODE in keys


def test_blind_measurements_mode_hides_fov_sliders():
    schema = _get_sun_tracking_schema(CoverType.BLIND, mode=FovMode.MEASUREMENTS)
    keys = _keys(schema)
    assert CONF_FOV_LEFT not in keys
    assert CONF_FOV_RIGHT not in keys
    # The mode selector itself stays so the user can switch back.
    assert CONF_FOV_MODE in keys


def test_blind_default_mode_is_angles():
    # No mode passed → behaves as ANGLES (sliders shown).
    schema = _get_sun_tracking_schema(CoverType.BLIND)
    keys = _keys(schema)
    assert CONF_FOV_LEFT in keys
    assert CONF_FOV_RIGHT in keys


def test_awning_never_gets_mode_selector():
    schema = _get_sun_tracking_schema(CoverType.AWNING, mode=FovMode.MEASUREMENTS)
    keys = _keys(schema)
    assert CONF_FOV_MODE not in keys
    # Awnings keep their fov sliders regardless of mode argument.
    assert CONF_FOV_LEFT in keys
    assert CONF_FOV_RIGHT in keys


# ----------------------------------------------------------------------------
# Save-path derivation (options flow)
# ----------------------------------------------------------------------------


def _options_flow(options: dict) -> OptionsFlowHandler:
    entry = MagicMock()
    entry.options = dict(options)
    entry.data = {"sensor_type": CoverType.BLIND}
    flow = OptionsFlowHandler(entry)
    flow.hass = MagicMock()
    flow.sensor_type = CoverType.BLIND
    flow.options = dict(options)
    flow.async_step_init = AsyncMock(return_value={"type": "menu"})
    return flow


@pytest.mark.asyncio
async def test_measurements_mode_stores_derived_fov():
    # width 2.0 / depth 0.5 → atan(2) ≈ 63°. The form was already in
    # Measurements mode (stored mode == MEASUREMENTS), so submitting it derives
    # and saves rather than re-rendering.
    flow = _options_flow(
        {
            CONF_WINDOW_WIDTH: 2.0,
            CONF_WINDOW_DEPTH: 0.5,
            CONF_FOV_LEFT: 90,
            CONF_FOV_RIGHT: 90,
            CONF_FOV_MODE: FovMode.MEASUREMENTS,
        }
    )
    await flow.async_step_sun_tracking(
        {
            CONF_FOV_MODE: FovMode.MEASUREMENTS,
            "distance_shaded_area": 0.5,
        }
    )
    assert flow.options[CONF_FOV_LEFT] == 63
    assert flow.options[CONF_FOV_RIGHT] == 63
    # window_depth itself is untouched.
    assert flow.options[CONF_WINDOW_DEPTH] == 0.5
    assert flow.options[CONF_FOV_MODE] == FovMode.MEASUREMENTS


@pytest.mark.asyncio
async def test_angles_mode_keeps_typed_fov():
    flow = _options_flow(
        {
            CONF_WINDOW_WIDTH: 2.0,
            CONF_WINDOW_DEPTH: 0.5,
        }
    )
    await flow.async_step_sun_tracking(
        {
            CONF_FOV_MODE: FovMode.ANGLES,
            CONF_FOV_LEFT: 30,
            CONF_FOV_RIGHT: 40,
            "distance_shaded_area": 0.5,
        }
    )
    assert flow.options[CONF_FOV_LEFT] == 30
    assert flow.options[CONF_FOV_RIGHT] == 40


@pytest.mark.asyncio
async def test_absent_fov_mode_behaves_as_angles():
    # Backward compat: no CONF_FOV_MODE in submission → typed fov untouched,
    # no derivation runs.
    flow = _options_flow({CONF_WINDOW_WIDTH: 2.0, CONF_WINDOW_DEPTH: 0.5})
    await flow.async_step_sun_tracking(
        {
            CONF_FOV_LEFT: 55,
            CONF_FOV_RIGHT: 65,
            "distance_shaded_area": 0.5,
        }
    )
    assert flow.options[CONF_FOV_LEFT] == 55
    assert flow.options[CONF_FOV_RIGHT] == 65


# ----------------------------------------------------------------------------
# Re-render on mode change
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switching_to_measurements_rerenders_form_not_next_step():
    # Form was built in ANGLES (the stored/default mode); submitting a different
    # mode must re-show the sun_tracking form, not advance to the next step.
    flow = _options_flow(
        {
            CONF_WINDOW_WIDTH: 2.0,
            CONF_WINDOW_DEPTH: 0.5,
            CONF_FOV_MODE: FovMode.ANGLES,
        }
    )
    advanced = False

    async def _next():
        nonlocal advanced
        advanced = True
        return {"type": "menu"}

    flow.async_step_init = _next
    result = await flow.async_step_sun_tracking(
        {
            CONF_FOV_MODE: FovMode.MEASUREMENTS,
            CONF_FOV_LEFT: 90,
            CONF_FOV_RIGHT: 90,
            "distance_shaded_area": 0.5,
        }
    )
    assert advanced is False
    assert result["type"] == "form"
    assert result["step_id"] == "sun_tracking"
    # The re-rendered form is in MEASUREMENTS mode (sliders hidden).
    assert CONF_FOV_LEFT not in _keys(result["data_schema"])

"""Tests for ``Coordinator.async_apply_user_position`` shared helper.

This helper is the single delegation point for any user-initiated cover
position command (the ``set_position`` integration service, the opt-in
proxy cover entity, future external triggers). It owns the min-mode floor
clamp + force-context build + ``apply_position`` dispatch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.adaptive_cover_pro.pipeline.types import (
    CustomPositionSensorState,
)


def _slot(pos: int, *, is_on: bool, min_mode: bool) -> CustomPositionSensorState:
    return CustomPositionSensorState(
        entity_id=f"binary_sensor.slot_{pos}",
        is_on=is_on,
        position=pos,
        priority=77,
        min_mode=min_mode,
        use_my=False,
    )


def _make_coord(custom_states, *, default_options=None):
    """Build a coordinator-shaped mock that exposes async_apply_user_position.

    We import the *real* method off the Coordinator class and bind it onto a
    MagicMock so we can drive it without a full HA setup.
    """
    from custom_components.adaptive_cover_pro.coordinator import (
        AdaptiveDataUpdateCoordinator,
    )

    coord = MagicMock(spec=AdaptiveDataUpdateCoordinator)
    coord.config_entry = MagicMock()
    coord.config_entry.options = default_options if default_options is not None else {}
    coord._read_custom_position_sensor_states.return_value = custom_states
    ctx = MagicMock(name="position_context")
    coord._build_position_context.return_value = ctx
    coord._cmd_svc = MagicMock()
    coord._cmd_svc.apply_position = AsyncMock(
        return_value=("sent", "set_cover_position")
    )

    # Bind the real method
    coord.async_apply_user_position = (
        AdaptiveDataUpdateCoordinator.async_apply_user_position.__get__(coord)
    )
    return coord, ctx


@pytest.mark.asyncio
async def test_async_apply_user_position_clamps_to_min_mode_floor() -> None:
    """Requested < highest active min-mode floor → clamped up to floor."""
    coord, ctx = _make_coord([_slot(40, is_on=True, min_mode=True)])

    await coord.async_apply_user_position("cover.test", 10, trigger="set_position")

    coord._cmd_svc.apply_position.assert_awaited_once_with(
        "cover.test", 40, "set_position", ctx
    )


@pytest.mark.asyncio
async def test_async_apply_user_position_passes_above_floor_unchanged() -> None:
    """Requested > floor → passes through unchanged."""
    coord, ctx = _make_coord([_slot(40, is_on=True, min_mode=True)])

    await coord.async_apply_user_position("cover.test", 80, trigger="proxy_slider")

    coord._cmd_svc.apply_position.assert_awaited_once_with(
        "cover.test", 80, "proxy_slider", ctx
    )


@pytest.mark.asyncio
async def test_async_apply_user_position_no_floors_uses_requested() -> None:
    """No active min-mode slots → requested value passes through."""
    coord, ctx = _make_coord(
        [_slot(80, is_on=True, min_mode=False), _slot(20, is_on=False, min_mode=True)]
    )

    await coord.async_apply_user_position("cover.test", 5, trigger="set_position")

    coord._cmd_svc.apply_position.assert_awaited_once_with(
        "cover.test", 5, "set_position", ctx
    )


@pytest.mark.asyncio
async def test_async_apply_user_position_uses_force_context() -> None:
    """_build_position_context must be called with force=True."""
    coord, _ctx = _make_coord([])
    await coord.async_apply_user_position("cover.test", 50, trigger="proxy_open")

    coord._build_position_context.assert_called_once()
    _, kwargs = coord._build_position_context.call_args
    assert kwargs.get("force") is True


@pytest.mark.asyncio
async def test_async_apply_user_position_accepts_trigger_label() -> None:
    """The trigger label is forwarded verbatim to ``apply_position``."""
    coord, ctx = _make_coord([])
    await coord.async_apply_user_position("cover.test", 33, trigger="proxy_tilt")
    coord._cmd_svc.apply_position.assert_awaited_once_with(
        "cover.test", 33, "proxy_tilt", ctx
    )


@pytest.mark.asyncio
async def test_async_apply_user_position_uses_passed_options_when_provided() -> None:
    """When ``options`` is passed, it overrides ``self.config_entry.options``."""
    entry_options = {"from": "entry"}
    coord, _ctx = _make_coord(
        [_slot(70, is_on=True, min_mode=True)], default_options=entry_options
    )
    custom_options = {"from": "override"}

    await coord.async_apply_user_position(
        "cover.test", 10, trigger="set_position", options=custom_options
    )

    coord._read_custom_position_sensor_states.assert_called_once_with(custom_options)
    # And the override flowed into _build_position_context too
    args, kwargs = coord._build_position_context.call_args
    # signature: (entity, options, *, force=...)
    assert args[1] is custom_options or kwargs.get("options") is custom_options

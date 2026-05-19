"""Default CoverTypePolicy hook behaviour for non-venetian cover types."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from custom_components.adaptive_cover_pro.cover_types.base import (
    POSITION_AXIS,
    CoverAxis,
    CoverTypePolicy,
)
from custom_components.adaptive_cover_pro.cover_types.blind import BlindPolicy


@pytest.mark.asyncio
async def test_maybe_update_tilt_only_default_is_noop() -> None:
    """Base-class maybe_update_tilt_only must return None without side-effects."""
    policy = BlindPolicy()
    result = await policy.maybe_update_tilt_only(
        "cover.x",
        current_position=42,
        context=MagicMock(),
        reason="solar",
    )
    assert result is None


class _MinimalStubPolicy(CoverTypePolicy):
    """The smallest legal CoverTypePolicy — only implements the abstract hook.

    Models a fifth cover type added later that forgets to override the
    config-flow hooks. The defaults on the base class must keep the flow
    functional without that override, so the config flow can't crash
    silently for a partial implementation.
    """

    cover_type = "cover_stub"
    axes: ClassVar[tuple[CoverAxis, ...]] = (POSITION_AXIS,)

    def build_calc_engine(self, **kwargs):  # type: ignore[override]
        return MagicMock()


def test_entity_selector_filter_default_is_plain_cover_domain() -> None:
    """The base default returns a plain cover-domain selector config."""
    flt = _MinimalStubPolicy().entity_selector_filter()
    assert flt["domain"] == "cover"
    # No capability requirement should be advertised by the default.
    assert "supported_features" not in flt


def test_geometry_schema_default_is_empty() -> None:
    """The base default returns an empty vol.Schema, not None."""
    schema = _MinimalStubPolicy().geometry_schema()
    assert isinstance(schema, vol.Schema)
    assert schema({}) == {}


def test_summary_geometry_lines_default_is_empty_list() -> None:
    """The base default returns ``[]`` so summary builders can extend unconditionally."""
    assert _MinimalStubPolicy().summary_geometry_lines({}) == []

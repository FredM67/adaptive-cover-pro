"""Vertical-blind cover policy."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..engine.covers import AdaptiveVerticalCover
from .base import CoverTypePolicy

if TYPE_CHECKING:
    from ..engine.covers import AdaptiveGeneralCover
    from ..services.configuration_service import ConfigurationService


class BlindPolicy(CoverTypePolicy):
    """Cover that moves vertically (raise/lower)."""

    cover_type = "cover_blind"

    def disallowed_geometry_fields(
        self,
        *,
        vertical_only: set[str],
        awning_only: set[str],
        tilt_only: set[str],
    ) -> list[tuple[set[str], str]]:
        """Reject awning and tilt geometry fields on a vertical blind."""
        return [(awning_only, "awning"), (tilt_only, "tilt")]

    def glare_zones_config(self, config_service, options: dict):
        """Return the glare-zones config for this cover (vertical-only feature)."""
        return config_service.get_glare_zones_config(options)

    def cover_capability_warnings(self, known: dict[str, dict]) -> list[str]:
        """Warn when no bound entity advertises ``set_position``."""
        if not any(caps.get("has_set_position") for caps in known.values()):
            return [
                "⚠️ Configured as vertical blind but no bound cover supports "
                "set_position — only open/close will be issued."
            ]
        return []

    def build_calc_engine(
        self,
        *,
        logger,
        sol_azi: float,
        sol_elev: float,
        sun_data,
        config,
        config_service: ConfigurationService,
        options: dict,
    ) -> AdaptiveGeneralCover:
        """Build an ``AdaptiveVerticalCover``, threading glare zones if any."""
        vert_config = config_service.get_vertical_data(options)
        glare_zones_cfg = config_service.get_glare_zones_config(options)
        if glare_zones_cfg is not None:
            vert_config = replace(vert_config, glare_zones=glare_zones_cfg)
        return AdaptiveVerticalCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            vert_config=vert_config,
        )

"""Horizontal-awning cover policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..engine.covers import AdaptiveHorizontalCover
from .base import CoverTypePolicy

if TYPE_CHECKING:
    from ..engine.covers import AdaptiveGeneralCover
    from ..services.configuration_service import ConfigurationService


class AwningPolicy(CoverTypePolicy):
    """Cover that extends horizontally (in/out)."""

    cover_type = "cover_awning"

    def disallowed_geometry_fields(
        self,
        *,
        vertical_only: set[str],
        awning_only: set[str],
        tilt_only: set[str],
    ) -> list[tuple[set[str], str]]:
        """Reject vertical-blind and tilt geometry fields on an awning cover."""
        return [(vertical_only, "vertical blind"), (tilt_only, "tilt")]

    def cover_capability_warnings(self, known: dict[str, dict]) -> list[str]:
        """Warn when no bound entity advertises ``set_position``."""
        if not any(caps.get("has_set_position") for caps in known.values()):
            return [
                "⚠️ Configured as awning but no bound cover supports "
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
        """Build an ``AdaptiveHorizontalCover`` for in/out awning geometry."""
        return AdaptiveHorizontalCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            vert_config=config_service.get_vertical_data(options),
            horiz_config=config_service.get_horizontal_data(options),
        )

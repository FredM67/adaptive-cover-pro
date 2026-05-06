"""Tilt-only cover policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..engine.covers import AdaptiveTiltCover
from .base import CoverTypePolicy

if TYPE_CHECKING:
    from ..engine.covers import AdaptiveGeneralCover
    from ..services.configuration_service import ConfigurationService


class TiltPolicy(CoverTypePolicy):
    """Cover that rotates slats only (no vertical movement)."""

    cover_type = "cover_tilt"

    def disallowed_geometry_fields(
        self,
        *,
        vertical_only: set[str],
        awning_only: set[str],
        tilt_only: set[str],
    ) -> list[tuple[set[str], str]]:
        """Reject vertical-blind and awning geometry fields on a tilt-only cover."""
        return [(vertical_only, "vertical blind"), (awning_only, "awning")]

    def cover_capability_warnings(self, known: dict[str, dict]) -> list[str]:
        """Warn when no bound entity advertises ``set_tilt_position``."""
        if not any(caps.get("has_set_tilt_position") for caps in known.values()):
            return [
                "⚠️ Configured as tilt (venetian) but no bound cover "
                "advertises set_tilt_position."
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
        """Build an ``AdaptiveTiltCover`` for slat-only covers."""
        return AdaptiveTiltCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            tilt_config=config_service.get_tilt_data(options),
        )

"""CoverTypePolicy base class.

One concrete subclass per supported cover type. The coordinator selects a
single instance via ``get_policy()`` at startup; every venetian-specific
decision (calc engine choice, post-pipeline tilt fill, manual-override
secondary axis, dual-axis cover-command sequencing) lives behind a hook
on this class so the shared code paths never branch on cover type.

Three of four cover types (blind, awning, tilt) implement only
``build_calc_engine``; the rest of the hooks default to no-ops. Venetian
overrides everything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from ..engine.covers import AdaptiveGeneralCover
    from ..pipeline.types import PipelineResult
    from ..services.configuration_service import ConfigurationService


class CoverTypePolicy(ABC):
    """Per-cover-type policy."""

    cover_type: ClassVar[str]

    @abstractmethod
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
        """Instantiate the calculation engine for this cover type."""

    def post_pipeline_resolve(
        self,
        result: PipelineResult,
        *,
        logger,
        sol_azi: float,
        sol_elev: float,
        sun_data,
        config,
        config_service: ConfigurationService,
        options: dict,
    ) -> PipelineResult:
        """Enrich the pipeline result. Default: identity."""
        return result

    def position_context_overrides(self, result: PipelineResult) -> dict[str, Any]:
        """Extra kwargs for ``PositionContext``. Default: empty."""
        return {}

    def secondary_axis_check(self, result: PipelineResult, cmd_svc) -> Any | None:
        """Return a manual-override secondary-axis check, or ``None``."""
        return None

    def attach(self, **kwargs: Any) -> None:
        """Bind late-resolved dependencies (cmd_svc, grace_mgr, …).

        Called by the coordinator after ``CoverCommandService`` is built.
        Policies that need a long-lived helper (e.g. ``VenetianPolicy``'s
        dual-axis sequencer) construct it here. Default: no-op.
        """
        return

    def is_in_tilt_suppression(self, entity_id: str) -> bool:  # noqa: ARG002
        """Return whether the tilt-axis suppression window is open.

        Default ``False`` for cover types without a back-rotating tilt axis.
        """
        return False

    async def after_position_command(
        self,
        cmd_svc,
        entity_id: str,
        *,
        service: str,
        position: int,
        context,
        reason: str,
    ) -> None:
        """Run any post-command work (default: no-op).

        Receives the actually-emitted ``service`` so policies can branch on
        which axis just fired (e.g. venetian only sequences after a position
        command, not after a direct tilt command).
        """
        return

    # ---- Config-flow / options-service helpers ------------------------- #

    def cover_capability_warnings(self, known: dict[str, dict]) -> list[str]:
        """Return user-facing warnings about the bound covers' capabilities.

        Default: no warnings — vertical / awning / tilt logic still lives in
        ``config_flow._check_cover_capabilities``. ``VenetianPolicy``
        overrides to express its dual-axis capability requirement.
        """
        return []

    def summary_extra_lines(self, config: dict[str, Any]) -> list[str]:
        """Extra lines for ``_build_config_summary``'s geometry section.

        Default: empty. ``VenetianPolicy`` overrides to surface its slat
        configuration alongside the window dimensions.
        """
        return []

    def glare_zones_config(self, config_service, options: dict) -> Any | None:
        """Return a ``GlareZonesConfig`` for this cover, or ``None``.

        Default ``None`` — only ``BlindPolicy`` reads its glare-zone config
        from options. Lets the coordinator populate the snapshot without
        branching on cover type.
        """
        return None

    def disallowed_geometry_fields(
        self,
        *,
        vertical_only: set[str],
        awning_only: set[str],
        tilt_only: set[str],
    ) -> list[tuple[set[str], str]]:
        """List ``(field_set, type_label)`` pairs that are invalid for this cover.

        ``options_service.validate_options_patch`` uses this to decide which
        cross-type geometry fields to reject. Default returns nothing — the
        caller must use this method to opt in (each registered policy
        implements it explicitly so we don't silently fail open).
        """
        return []

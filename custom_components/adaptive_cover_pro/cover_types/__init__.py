"""Per-cover-type policy registry.

The coordinator selects a single ``CoverTypePolicy`` instance at startup
and routes every cover-type-specific decision through it, so the shared
code paths (coordinator update cycle, cover command service, manual
override detection, config flow) never branch on cover type.
"""

from __future__ import annotations

from .awning import AwningPolicy
from .base import CoverTypePolicy
from .blind import BlindPolicy
from .tilt import TiltPolicy
from .venetian import VenetianPolicy

POLICY_REGISTRY: dict[str, type[CoverTypePolicy]] = {
    BlindPolicy.cover_type: BlindPolicy,
    AwningPolicy.cover_type: AwningPolicy,
    TiltPolicy.cover_type: TiltPolicy,
    VenetianPolicy.cover_type: VenetianPolicy,
}


def get_policy(cover_type: str | None) -> CoverTypePolicy:
    """Return a policy instance for the given cover-type string.

    Raises ``ValueError`` for unknown cover types — preserves the failure
    mode of the previous if/elif chain in ``coordinator.get_blind_data``.
    """
    cls = POLICY_REGISTRY.get(cover_type) if cover_type is not None else None
    if cls is None:
        msg = f"Unsupported cover type: {cover_type!r}"
        raise ValueError(msg)
    return cls()


__all__ = [
    "POLICY_REGISTRY",
    "AwningPolicy",
    "BlindPolicy",
    "CoverTypePolicy",
    "TiltPolicy",
    "VenetianPolicy",
    "get_policy",
]

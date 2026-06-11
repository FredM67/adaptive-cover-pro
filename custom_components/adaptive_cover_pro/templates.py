"""Runtime resolution of templated threshold options (issue #577).

Threshold config fields in :data:`config_fields.TEMPLATABLE_KEYS` may hold a
Home Assistant Jinja2 template string instead of a fixed number. The template is
rendered to a float once per coordinator update cycle, at the coordinator
boundary, so the pure calculation engine and ``RuntimeConfig`` never see a raw
template string.

A render or coercion failure never propagates into the update cycle: the
offending key is dropped from the returned options so the field falls back to its
declared default, and a warning is logged once per failure transition.
"""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template

from .config_fields import TEMPLATABLE_KEYS

_LOGGER = logging.getLogger(__name__)


def is_template_string(value) -> bool:
    """Return True if *value* is a string carrying Jinja2 template markup.

    Stricter than :func:`_looks_templated`: a plain numeric string like
    ``"1000"`` is *not* a template. Shared by the service validators and the
    diagnostics builder so "is this actually a template?" is decided in one
    place.
    """
    return isinstance(value, str) and ("{{" in value or "{%" in value)


def _looks_templated(value) -> bool:
    """Return True if *value* is a string that needs rendering.

    Any string is a candidate: a plain numeric string (``"1000"``) renders to
    itself, and a Jinja string (``"{{ ... }}"``) renders to its result. Numeric
    values stored by the legacy ``NumberSelector`` are ``int``/``float`` and are
    passed through untouched.
    """
    return isinstance(value, str)


class TemplateResolver:
    """Render templated threshold options to numbers, once per cycle."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Store *hass* for template rendering."""
        self._hass = hass
        # Keys currently in a failed-render state — used to log each failure
        # transition once instead of every cycle.
        self._failed: set[str] = set()

    def resolve(self, options: dict) -> dict:
        """Return *options* with templatable string values rendered to floats.

        Fast path: when no templatable key holds a string, return *options*
        unchanged (no copy). Otherwise return a shallow copy with each rendered
        key replaced by its float result, or stripped if rendering failed.
        """
        if not any(_looks_templated(options.get(key)) for key in TEMPLATABLE_KEYS):
            self._failed.clear()
            return options

        resolved = dict(options)
        for key in TEMPLATABLE_KEYS:
            value = resolved.get(key)
            if not _looks_templated(value):
                continue
            rendered = self._render(key, value)
            if rendered is None:
                # Drop so the consumer falls back to the field default.
                resolved.pop(key, None)
            else:
                resolved[key] = rendered
        return resolved

    def _render(self, key: str, value: str) -> float | None:
        """Render *value* to a float, or None on failure."""
        try:
            result = Template(value, self._hass).async_render(parse_result=False)
            number = float(str(result).strip())
        except (TemplateError, ValueError, TypeError) as err:
            if key not in self._failed:
                self._failed.add(key)
                _LOGGER.warning(
                    "Template for %s failed to render to a number (%r): %s; "
                    "falling back to default",
                    key,
                    value,
                    err,
                )
            return None
        self._failed.discard(key)
        return number

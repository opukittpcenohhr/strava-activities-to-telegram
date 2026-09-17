"""Typed datetimes for OmegaConf fields using allow_objects=True.

OmegaConf passes resolved values through unchanged for custom scalar types.
The owning config section calls OmegaConfDateTime.parse in __post_init__ to convert them.
"""

from datetime import datetime, timezone
from typing import Self, overload


class OmegaConfDateTime(datetime):
    """A datetime with ISO parsing and UTC defaults for configuration/API input."""

    @overload
    @classmethod
    def parse(cls, value: str | datetime, *, field: str = 'datetime') -> Self: ...

    @overload
    @classmethod
    def parse(cls, value: None, *, field: str = 'datetime') -> None: ...

    @classmethod
    def parse(cls, value: str | datetime | None, *, field: str = 'datetime') -> Self | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            value = value.isoformat()
        if not isinstance(value, str):
            raise ValueError(f'{field} must be an ISO date or timestamp')
        try:
            parsed = cls.fromisoformat(value)
        except ValueError:
            raise ValueError(f'{field} must be an ISO date or timestamp') from None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

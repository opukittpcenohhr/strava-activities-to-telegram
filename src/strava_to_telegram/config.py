"""YAML configuration mapped into typed, nested dataclasses.

Each section validates itself in its own module's `__post_init__`, so parsing a
configuration is what rejects a bad value. What stays here is composition,
parsing, path resolution, and the presence checks that depend on which command
is about to run.
"""

from dataclasses import dataclass, fields, is_dataclass, replace
from collections.abc import Iterable
from typing import Any, cast
from pathlib import Path

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from .auth import AuthConfig
from .logs import LoggingConfig
from .maps import MapConfig
from .strava import StravaConfig
from .telegram import TelegramConfig
from .storage.database import StorageConfig
from .sync import SyncConfig


@dataclass
class Config:
    storage: StorageConfig
    strava: StravaConfig
    telegram: TelegramConfig
    map: MapConfig
    sync: SyncConfig
    auth: AuthConfig
    logging: LoggingConfig


def resolve_paths(config: Any, base: Path) -> Any:
    """Normalize every Path field, including future nested config fields."""
    values = {}
    for item in fields(config):
        value = getattr(config, item.name)
        if is_dataclass(value):
            value = resolve_paths(value, base)
        elif isinstance(value, Path):
            value = (base / value.expanduser()).resolve()
        values[item.name] = value
    return replace(config, **values)


def from_mapping(data: Any, base: Path, *, overrides: Iterable[str] = ()) -> Config:
    """Build a Config from an already-parsed mapping.

    Split from `load_config` so that interpreting a configuration is testable
    without a file on disk: `base` is what relative paths resolve against, rather
    than being derived from a file location.
    """
    for item in overrides:
        # `from_dotlist` turns a valueless key into None, which merges silently into
        # any nullable field. Every other malformed form fails at merge, naming the
        # offending key, so this is the only shape worth checking here.
        # Not echoed: a user who typed `strava.client_secret abc123` instead of
        # `strava.client_secret=abc123` would put the value in this message.
        if '=' not in item:
            raise ValueError('Overrides must use dotted.key=value syntax')
    try:
        # Dataclass schema enforces known fields and converts compatible scalar types.
        # Custom OmegaConfDateTime fields pass through to their section's __post_init__
        # for parsing and validation after interpolation and overrides.
        merged = OmegaConf.merge(
            OmegaConf.structured(Config, flags={'allow_objects': True}), data, OmegaConf.from_dotlist(list(overrides))
        )
        missing = OmegaConf.missing_keys(merged)
        if missing:
            raise ValueError('Missing required settings: ' + ', '.join(sorted(missing)))
        # OmegaConf cannot express that a structured config round-trips to its schema.
        config = cast(Config, OmegaConf.to_object(merged))
    except OmegaConfBaseException as error:
        full_key = getattr(error, 'full_key', None)
        where = f' at {full_key}' if full_key else ''
        raise ValueError(f'Invalid configuration{where}; check field names, types and interpolations') from None
    return resolve_paths(config, base.resolve())


def load_config(path: Path | str = 'config.yaml', *, overrides: Iterable[str] = ()) -> Config:
    resolved = Path(path).expanduser().resolve()
    try:
        data = OmegaConf.load(resolved)
    except FileNotFoundError:
        # Only this case means "you have not made a config yet". OmegaConf also raises
        # OSError for a wrong top-level type, and its message says so more precisely.
        raise ValueError(f'Cannot read configuration: {resolved}; copy config.example.yaml first') from None
    # A YAML syntax error propagates as PyYAML raised it, because its message carries
    # the line and column. It reports position and structure, not scalar values.
    return from_mapping(data, resolved.parent, overrides=overrides)

"""Logging setup and the configuration that controls it.

Logging must work before configuration exists, because failing to read the
configuration is itself something to report. `start` installs a usable baseline at
import time of the command; `apply` adjusts it once a configuration has loaded.
"""
from dataclasses import dataclass
import logging


FORMAT = '%(asctime)s %(levelname)s %(message)s'


@dataclass
class LoggingConfig:
    level: str

    def __post_init__(self) -> None:
        if self.level not in logging.getLevelNamesMapping():
            raise ValueError('logging.level must be a standard level name, such as INFO or DEBUG')


def start() -> None:
    """Baseline logging, active before any configuration has been read."""
    logging.basicConfig(level=logging.INFO, format=FORMAT)


def apply(config: LoggingConfig) -> None:
    """Adjust verbosity once configuration has loaded."""
    logging.getLogger().setLevel(getattr(logging, config.level))

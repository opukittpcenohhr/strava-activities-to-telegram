import os
from pathlib import Path
from typing import Annotated

import typer

from .auth import authorize
from .strava import Strava
from .telegram import Telegram
from .config import Config, load_config
from . import logs
from .storage.database import Database, database
from .sync import publish_last_activity, sync_once

# pretty_exceptions_enable stays False: Typer's rich tracebacks render local
# variables, and those hold the credentials loaded from config.yaml.
app = typer.Typer(help='Sync Strava activities to Telegram.',
                  no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)
Overrides = Annotated[list[str] | None, typer.Argument(
    help='Config overrides: dotted.key=value (for example auth.port=9000).')]


@app.callback()
def configure(ctx: typer.Context,
              config: Annotated[Path, typer.Option('--config', help='YAML configuration file.')] = Path('config.yaml')) -> None:
    ctx.obj = config


def command_config(ctx: typer.Context, overrides: list[str] | None) -> Config:
    config = load_config(ctx.obj, overrides=overrides or [])
    logs.apply(config.logging)
    return config


def services(db: Database, config: Config) -> tuple[Strava, Telegram, str]:
    """Activity source, Telegram client, and destination chat for one sync pass."""
    return (Strava(db, config.strava),
            Telegram(config.telegram.bot_token),
            config.telegram.chat)


@app.command('auth')
def auth_command(ctx: typer.Context, overrides: Overrides = None) -> None:
    """Authorize your Strava account once."""
    config = command_config(ctx, overrides)
    with database(config.storage.database) as db:
        authorize(db, config.auth, config.strava)


@app.command('post-last')
def post_last_command(ctx: typer.Context, overrides: Overrides = None) -> None:
    """Always post the latest activity, ignoring sync filters and existing posts."""
    config = command_config(ctx, overrides)
    with database(config.storage.database) as db:
        source, telegram, chat = services(db, config)
        publish_last_activity(db, source, telegram, chat)


@app.command('sync')
def sync_command(ctx: typer.Context, overrides: Overrides = None) -> None:
    """Perform one synchronization pass. Schedule this with cron."""
    config = command_config(ctx, overrides)
    with database(config.storage.database) as db:
        source, telegram, chat = services(db, config)
        sync_once(db, source, telegram, chat, config.sync)


def main() -> None:
    # Owner-only for everything created below: the database holds Strava tokens.
    os.umask(0o077)

    logs.start()
    app()


if __name__ == '__main__':
    main()

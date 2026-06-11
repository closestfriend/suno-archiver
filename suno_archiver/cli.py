"""Command-line interface."""

import sys

import click
from dotenv import load_dotenv

from . import __version__
from .auth import AuthError, build_session, cookie_candidates
from .core import SunoArchiver
from .suno_api import SunoApi, SunoApiError


def _build_archiver(**kwargs):
    api = SunoApi(build_session())
    return SunoArchiver(api, **kwargs)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="suno-archiver")
@click.option("-s", "--since", help='Archive clips created since ("2026-01-15", "2 weeks ago")')
@click.option("-u", "--until", help="Archive clips created until this date")
@click.option("-l", "--last-run", is_flag=True, help="Incremental: only clips since the last successful run")
@click.option("--wav", is_flag=True, help="Also fetch WAVs (slow: requests conversion per song)")
@click.option("--dir", "archive_dir", default="suno_archive", show_default=True,
              help="Archive root directory")
@click.pass_context
def main(ctx, since, until, last_run, wav, archive_dir):
    """Archive your Suno library: audio, cover art, and complete metadata."""
    load_dotenv()
    if ctx.invoked_subcommand is not None:
        return
    if last_run and (since or until):
        raise click.UsageError("--last-run cannot be combined with --since/--until")
    try:
        archiver = _build_archiver(archive_dir=archive_dir, since=since,
                                   until=until, last_run=last_run, want_wav=wav)
        archiver.run()
        if not archiver.clips and not archiver.fetch_complete:
            sys.exit(1)
    except (AuthError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
def doctor():
    """Diagnose auth and API health step by step."""
    load_dotenv()
    click.echo("1. Looking for Suno session cookie(s)...")
    first = next(iter(cookie_candidates()), None)
    if first is not None:
        click.echo("   ok: session cookie found")
    else:
        from .auth import _AUTH_ERROR_MESSAGE
        click.echo(f"   FAIL: {_AUTH_ERROR_MESSAGE}")
        sys.exit(1)

    click.echo("2. Exchanging cookie for a token (Clerk)...")
    try:
        session = build_session()
        click.echo("   ok: token minted")
    except AuthError as e:
        click.echo(f"   FAIL: {e}")
        click.echo("   Your session may be expired: log into suno.com and retry.")
        sys.exit(1)

    click.echo("3. Fetching library page 1...")
    api = SunoApi(session)
    try:
        clips = api.list_library(page=0)
        click.echo(f"   ok: {len(clips)} clips on page 1")
    except SunoApiError as e:
        click.echo(f"   FAIL: {e}")
        click.echo("   Auth works but the feed endpoint failed — Suno may have "
                   "changed their API. Check for a newer suno-archiver release.")
        sys.exit(1)

    click.echo("\nAll good. You're ready to run: suno-archiver")


if __name__ == "__main__":
    main()

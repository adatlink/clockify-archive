from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .api import ClockifyClient
from .archive import ArchiveOptions, Archiver
from .config import CONFIG_CANDIDATES, load_settings, write_example_config
from .util import iso_z, normalize_datetime_arg


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clockify-archive",
        description="Export a Clockify workspace into a portable JSON + CSV + SQLite archive.",
    )
    p.add_argument("output", nargs="?", default=".", help="Output root directory (default: current directory); explicit .zip paths remain supported for backward compatibility")
    p.add_argument("-w", "--workspace", help="Workspace ID or exact workspace name")
    p.add_argument("--api-key", help="Clockify API key (prefer CLOCKIFY_API_KEY or config file)")
    p.add_argument("--base-url", help="Clockify API base URL; useful for regional/subdomain deployments")
    p.add_argument("--config", help="TOML config path")
    p.add_argument("--from", dest="date_from", default="1970-01-01", help="Archive entries from this date/time (default: 1970-01-01)")
    p.add_argument("--to", dest="date_to", help="Archive entries through this date/time (default: now)")
    p.add_argument("--no-raw", action="store_true", help="Do not include raw JSON")
    p.add_argument("--no-csv", action="store_true", help="Do not include normalized CSV files")
    p.add_argument("--no-sqlite", action="store_true", help="Do not include SQLite database")
    p.add_argument("--no-receipts", action="store_true", help="Do not download expense receipt attachments")
    p.add_argument("--no-deleted", action="store_true", help="Do not attempt the experimental deleted-entities export")
    p.add_argument("--strict", action="store_true", help="Fail if an optional paid/permission-protected endpoint cannot be archived")
    p.add_argument(
        "--zip",
        action="store_true",
        dest="create_zip",
        help="Also create a ZIP copy (inside the direct output directory, or beside it when --archive-subdir is used)",
    )
    p.add_argument("--date-subdirs", action="store_true", help="Create YEAR/MONTH/DAY subdirectories below the output root using the export date (UTC)")
    p.add_argument(
        "--archive-subdir",
        action="store_true",
        help="Place the export inside a clockify-WORKSPACE-DATE-TIME subdirectory instead of writing directly to the output directory",
    )
    p.add_argument("--csv-delimiter", default=",", choices=[",", ";", "\t"], help="Delimiter for normalized CSV files")
    p.add_argument("--list-workspaces", action="store_true", help="List visible workspaces and exit")
    p.add_argument("--init-config", nargs="?", const=str(CONFIG_CANDIDATES[0]), help="Write an example config file and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _client_from_args(args: argparse.Namespace) -> tuple[ClockifyClient, str | None]:
    cfg = load_settings(args.config)
    api_key = args.api_key or cfg.api_key
    workspace = args.workspace or cfg.workspace
    base_url = args.base_url or cfg.base_url
    if not api_key:
        raise RuntimeError("Clockify API key is required. Set CLOCKIFY_API_KEY, --api-key, or a TOML config file.")
    return ClockifyClient(api_key, base_url), workspace


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.init_config:
            path = Path(args.init_config).expanduser()
            write_example_config(path)
            print(path)
            return 0

        client, workspace = _client_from_args(args)
        if args.list_workspaces:
            values = client.get("/workspaces").data or []
            for w in values:
                print(f"{w.get('id')}\t{w.get('name')}")
            return 0

        start = normalize_datetime_arg(args.date_from, end_of_day=False)
        end = normalize_datetime_arg(args.date_to, end_of_day=True) if args.date_to else iso_z(datetime.now(timezone.utc))
        assert start and end
        if start > end:
            raise RuntimeError("--from must be earlier than --to")

        options = ArchiveOptions(
            workspace=workspace,
            output=Path(args.output).expanduser().resolve(),
            start=start,
            end=end,
            raw=not args.no_raw,
            csv=not args.no_csv,
            sqlite=not args.no_sqlite,
            receipts=not args.no_receipts,
            include_deleted=not args.no_deleted,
            strict=args.strict,
            create_zip=args.create_zip,
            date_subdirs=args.date_subdirs,
            archive_subdir=args.archive_subdir,
            csv_delimiter=args.csv_delimiter,
            verbose=args.verbose,
        )
        result = Archiver(client, options).run()
        print(result.zip_path if result.zip_path is not None else result.archive_dir)
        if result.warnings:
            print(f"Completed with {len(result.warnings)} warning(s). See manifest.json inside the archive directory.", file=sys.stderr)
        return 0
    except (RuntimeError, ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point.

Examples:
  python -m confluence_export --page 3390078977
  python -m confluence_export --url "https://pdco-sw.atlassian.net/wiki/spaces/IE/pages/3390078977/..."
  python -m confluence_export --tree 3390078977          # page + all child pages
  python -m confluence_export --space IE --limit 100
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

from .client import ConfluenceClient
from .export import Exporter

_PAGE_ID_IN_URL = re.compile(r"/pages/(\d+)")


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def page_id_from_url(url: str) -> str:
    m = _PAGE_ID_IN_URL.search(url)
    if not m:
        raise argparse.ArgumentTypeError(f"No page id found in URL: {url}")
    return m.group(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="confluence_export", description="Export Confluence pages to Markdown.")
    ap.add_argument("--page", action="append", default=[], metavar="ID", help="Page id (repeatable)")
    ap.add_argument("--url", action="append", default=[], metavar="URL", help="Page URL (repeatable)")
    ap.add_argument("--tree", action="append", default=[], metavar="ID", help="Page id plus all descendants")
    ap.add_argument("--space", action="append", default=[], metavar="KEY", help="Every current page in a space")
    ap.add_argument("--limit", type=int, default=0, help="Max pages per --space/--tree (0 = no limit)")
    ap.add_argument("--out", default=os.getenv("EXPORT_DIR", "output"), help="Output folder (default: output)")
    ap.add_argument("--force", action="store_true", help="Re-export even if the page version is unchanged")
    ap.add_argument("--no-user-lookup", action="store_true", help="Don't resolve @mentions to display names")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not (args.page or args.url or args.tree or args.space):
        ap.error("give at least one of --page, --url, --tree or --space")
    return args


def _take(it, limit: int) -> list[str]:
    out = []
    for x in it:
        out.append(x)
        if limit and len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    missing = [v for v in ("CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_TOKEN") if not os.getenv(v)]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)} (see .env.example)", file=sys.stderr)
        return 2

    client = ConfluenceClient(os.environ["CONFLUENCE_BASE_URL"], os.environ["CONFLUENCE_EMAIL"],
                              os.environ["CONFLUENCE_TOKEN"])

    ids: list[str] = list(args.page) + [page_id_from_url(u) for u in args.url]
    for root in args.tree:
        ids.append(root)
        ids += _take(client.iter_descendant_page_ids(root), args.limit)
    for key in args.space:
        ids += _take(client.iter_space_page_ids(key), args.limit)

    exporter = Exporter(client, Path(args.out), force=args.force, resolve_users=not args.no_user_lookup)
    result = exporter.export_many(ids)
    print(f"\nDone: {len(result.written)} written, {len(result.skipped)} unchanged, {len(result.failed)} failed"
          f" -> {Path(args.out).resolve()}")
    for pid, err in result.failed.items():
        print(f"  FAILED {pid}: {err}", file=sys.stderr)
    return 1 if result.failed else 0

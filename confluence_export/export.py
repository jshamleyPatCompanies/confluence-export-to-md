"""Fetch pages, convert them, write Markdown with frontmatter, track state."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .client import ConfluenceClient
from .convert import storage_to_markdown

log = logging.getLogger(__name__)

STATE_FILE = ".export-state.json"


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "page"


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # JSON strings are valid YAML scalars


def build_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_yaml_str(str(v))}" for v in value)
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_yaml_str(str(value))}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


@dataclass
class ExportResult:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


class Exporter:
    def __init__(self, client: ConfluenceClient, out_dir: Path, force: bool = False,
                 resolve_users: bool = True):
        self.client = client
        self.out_dir = Path(out_dir)
        self.force = force
        self.resolve_users = resolve_users
        self.state_path = self.out_dir / STATE_FILE
        self.state: dict[str, dict] = self._load_state()

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {}

    def save_state(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")

    def export_many(self, page_ids: list[str]) -> ExportResult:
        result = ExportResult()
        seen: set[str] = set()
        for pid in page_ids:
            if pid in seen:
                continue
            seen.add(pid)
            try:
                if self.export_page(pid):
                    result.written.append(pid)
                else:
                    result.skipped.append(pid)
            except Exception as e:  # keep going; report at the end
                log.error("page %s failed: %s", pid, e)
                result.failed[pid] = str(e)
            self.save_state()  # save as we go so a crash doesn't lose progress
        return result

    def export_page(self, page_id: str) -> bool:
        """Returns True if a file was written, False if skipped as unchanged."""
        page = self.client.get_page(page_id, with_body=True)
        version = page["version"]["number"]
        prev = self.state.get(page_id)
        if prev and prev.get("version") == version and not self.force \
                and (self.out_dir / prev["path"]).exists():
            log.info("unchanged: %s (v%s)", page["title"], version)
            return False

        space = self.client.get_space_by_id(page["spaceId"])
        resolver = self.client.get_user_name if self.resolve_users else None
        body_md = storage_to_markdown(page["body"]["storage"]["value"], resolver)

        meta = {
            "title": page["title"],
            "page_id": page_id,
            "space_key": space["key"],
            "space_name": space.get("name", ""),
            "source_url": self.client.web_url(page),
            "breadcrumb": self.client.get_ancestor_titles(page_id),
            "labels": self.client.get_labels(page_id),
            "version": version,
            "last_updated": page["version"].get("createdAt", ""),
        }
        rel_path = Path(space["key"]) / f"{slugify(page['title'])}-{page_id}.md"
        path = self.out_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_frontmatter(meta) + f"# {page['title']}\n\n" + body_md, encoding="utf-8")

        # Page renamed or moved spaces: remove the stale file we wrote earlier.
        if prev and prev.get("path") and Path(prev["path"]) != rel_path:
            old = self.out_dir / prev["path"]
            if old.exists():
                old.unlink()

        self.state[page_id] = {"version": version, "path": rel_path.as_posix(), "title": page["title"]}
        log.info("wrote: %s", rel_path.as_posix())
        return True

"""Thin Confluence Cloud REST v2 client (read-only)."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, token: str, timeout: int = 30):
        # base_url like https://pdco-sw.atlassian.net (with or without /wiki)
        self.site = base_url.rstrip("/").removesuffix("/wiki")
        self.wiki = f"{self.site}/wiki"
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.session.headers["Accept"] = "application/json"
        self.timeout = timeout
        self._space_cache: dict[str, dict] = {}
        self._page_meta_cache: dict[str, dict] = {}
        self._user_cache: dict[str, str] = {}

    # ---- HTTP -----------------------------------------------------------
    def _get(self, url: str, params: dict | None = None, retries: int = 5) -> dict:
        if url.startswith("/"):
            url = self.site + url
        for attempt in range(retries):
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code in (429, 502, 503, 504):
                wait = float(r.headers.get("Retry-After", 2 ** attempt))
                log.warning("HTTP %s, retrying in %.0fs", r.status_code, wait)
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                raise PermissionError(
                    f"HTTP {r.status_code} for {url}. Check CONFLUENCE_EMAIL/CONFLUENCE_TOKEN, "
                    "page permissions, or whether your org blocks API tokens."
                )
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return r.json()

    def _paginate(self, url: str, params: dict | None = None) -> Iterator[dict]:
        params = dict(params or {})
        params.setdefault("limit", 100)
        while url:
            data = self._get(url, params)
            yield from data.get("results", [])
            url = data.get("_links", {}).get("next")
            params = None  # next link already carries the query string

    # ---- Pages ----------------------------------------------------------
    def get_page(self, page_id: str, with_body: bool = True) -> dict:
        params = {"body-format": "storage"} if with_body else {}
        return self._get(f"{self.wiki}/api/v2/pages/{page_id}", params)

    def get_page_meta(self, page_id: str) -> dict:
        if page_id not in self._page_meta_cache:
            self._page_meta_cache[page_id] = self.get_page(page_id, with_body=False)
        return self._page_meta_cache[page_id]

    def get_labels(self, page_id: str) -> list[str]:
        return [l["name"] for l in self._paginate(f"{self.wiki}/api/v2/pages/{page_id}/labels")]

    def get_ancestor_titles(self, page_id: str) -> list[str]:
        data = self._get(f"{self.wiki}/api/v2/pages/{page_id}/ancestors")
        titles = []
        for a in data.get("results", []):  # ordered root -> parent
            if a.get("type", "page") != "page":
                continue
            try:
                titles.append(self.get_page_meta(a["id"])["title"])
            except Exception:  # ancestor may be restricted
                pass
        return titles

    def iter_space_page_ids(self, space_key: str) -> Iterator[str]:
        space = self.get_space_by_key(space_key)
        for p in self._paginate(
            f"{self.wiki}/api/v2/spaces/{space['id']}/pages", {"status": "current"}
        ):
            yield p["id"]

    MAX_DESCENDANT_DEPTH = 5  # API maximum per call

    def iter_descendant_page_ids(self, page_id: str) -> Iterator[str]:
        """All pages under page_id at any depth (root not included).

        The descendants endpoint only goes 5 levels deep per call, so items at the
        deepest level are queried again to continue down the tree.
        """
        seen: set[str] = set()
        queue = [page_id]
        while queue:
            root = queue.pop(0)
            for d in self._paginate(f"{self.wiki}/api/v2/pages/{root}/descendants",
                                    {"depth": self.MAX_DESCENDANT_DEPTH}):
                if d["id"] in seen:
                    continue
                seen.add(d["id"])
                if d.get("type", "page") == "page":
                    yield d["id"]
                if d.get("depth", 0) >= self.MAX_DESCENDANT_DEPTH and d.get("type", "page") == "page":
                    queue.append(d["id"])

    # ---- Spaces / users -------------------------------------------------
    def get_space_by_key(self, key: str) -> dict:
        if key not in self._space_cache:
            results = self._get(f"{self.wiki}/api/v2/spaces", {"keys": key}).get("results", [])
            if not results:
                raise ValueError(f"Space '{key}' not found or not visible to you")
            self._space_cache[key] = results[0]
        return self._space_cache[key]

    def get_space_by_id(self, space_id: str) -> dict:
        for s in self._space_cache.values():
            if str(s["id"]) == str(space_id):
                return s
        s = self._get(f"{self.wiki}/api/v2/spaces/{space_id}")
        self._space_cache[s["key"]] = s
        return s

    def get_user_name(self, account_id: str) -> str:
        if account_id not in self._user_cache:
            try:
                u = self._get(f"{self.wiki}/rest/api/user", {"accountId": account_id})
                self._user_cache[account_id] = u.get("displayName") or account_id
            except Exception:
                self._user_cache[account_id] = "unknown user"
        return self._user_cache[account_id]

    def web_url(self, page: dict) -> str:
        return self.wiki + page.get("_links", {}).get("webui", f"/pages/{page['id']}")

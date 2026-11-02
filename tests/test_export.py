import json

from confluence_export.cli import page_id_from_url
from confluence_export.export import Exporter, build_frontmatter, slugify


class FakeClient:
    def __init__(self):
        self.version = 1
        self.title = "Eaglesoft Event Writebacks - MVP for 25.20"
        self.body_calls = 0

    def get_page(self, page_id, with_body=True):
        self.body_calls += 1
        return {
            "id": page_id, "title": self.title, "spaceId": "99",
            "version": {"number": self.version, "createdAt": "2026-04-06T12:00:00Z"},
            "body": {"storage": {"value": "<h2>Initiative</h2><p>Hello</p>"}},
            "_links": {"webui": f"/spaces/IE/pages/{page_id}/x"},
        }

    def get_space_by_id(self, sid):
        return {"id": sid, "key": "IE", "name": "Interoperability Ecosystem"}

    def get_ancestor_titles(self, pid):
        return ["Interoperability Ecosystem Home"]

    def get_labels(self, pid):
        return ["integrator", "mvp"]

    def get_user_name(self, acc):
        return acc

    def web_url(self, page):
        return "https://pdco-sw.atlassian.net/wiki" + page["_links"]["webui"]


def test_slugify():
    assert slugify("Eaglesoft Event Writebacks - MVP for 25.20") == "eaglesoft-event-writebacks-mvp-for-25-20"
    assert slugify("!!!") == "page"


def test_frontmatter_quotes_and_lists():
    fm = build_frontmatter({"title": 'Say "hi": yes', "labels": ["a"], "empty": [], "version": 3})
    assert 'title: "Say \\"hi\\": yes"' in fm
    assert "labels:\n  - \"a\"" in fm
    assert "empty: []" in fm
    assert "version: 3" in fm


def test_page_id_from_url():
    url = "https://pdco-sw.atlassian.net/wiki/spaces/IE/pages/3390078977/Eaglesoft+Event+Writebacks"
    assert page_id_from_url(url) == "3390078977"


def test_export_writes_then_skips_then_rewrites_on_rename(tmp_path):
    client = FakeClient()
    ex = Exporter(client, tmp_path)
    r = ex.export_many(["3390078977"])
    assert r.written == ["3390078977"]

    f = tmp_path / "IE" / "eaglesoft-event-writebacks-mvp-for-25-20-3390078977.md"
    text = f.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert 'source_url: "https://pdco-sw.atlassian.net/wiki/spaces/IE/pages/3390078977/x"' in text
    assert "# Eaglesoft Event Writebacks - MVP for 25.20" in text
    assert "## Initiative" in text

    # Same version -> skipped, using persisted state
    ex2 = Exporter(client, tmp_path)
    assert ex2.export_many(["3390078977"]).skipped == ["3390078977"]

    # Renamed + new version -> new file, old file removed
    client.version, client.title = 2, "Writebacks MVP"
    ex3 = Exporter(client, tmp_path)
    assert ex3.export_many(["3390078977"]).written == ["3390078977"]
    assert not f.exists()
    assert (tmp_path / "IE" / "writebacks-mvp-3390078977.md").exists()
    state = json.loads((tmp_path / ".export-state.json").read_text())
    assert state["3390078977"]["version"] == 2


def test_tree_goes_deeper_than_api_depth_limit():
    from confluence_export.client import ConfluenceClient

    # Linear chain 1 -> 2 -> ... -> 12; the API returns at most 5 levels per call.
    class Chain(ConfluenceClient):
        def __init__(self):
            pass

        def _paginate(self, url, params=None):
            root = int(url.split("/pages/")[1].split("/")[0])
            depth = params["depth"]
            for lvl in range(1, depth + 1):
                child = root + lvl
                if child <= 12:
                    yield {"id": str(child), "type": "page", "depth": lvl}

        wiki = "https://x/wiki"

    ids = list(Chain().iter_descendant_page_ids("1"))
    assert ids == [str(i) for i in range(2, 13)]

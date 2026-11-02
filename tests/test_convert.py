from pathlib import Path

from confluence_export.convert import storage_to_markdown

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_storage.html").read_text(encoding="utf-8")


def md():
    return storage_to_markdown(FIXTURE, resolve_user=lambda acc: "Jeff Shamley" if acc == "abc123" else acc)


def test_headings_and_inline():
    out = md()
    assert "## Overview" in out
    assert "**phone-home**" in out
    assert "### Status" in out


def test_user_mention_resolved():
    assert "@Jeff Shamley" in md()


def test_toc_dropped_and_params_hidden():
    out = md()
    assert "maxLevel" not in out
    assert "toc" not in out.lower().split("overview")[1][:50]


def test_info_panel_becomes_blockquote():
    assert "> **Info: Heads up**" in md()
    assert "> Uses Platform Registration client credentials." in md()


def test_table_and_status():
    out = md()
    assert "| Team | Status |" in out
    assert "| Platform | [IN PROGRESS] |" in out


def test_code_block_preserved_with_language():
    out = md()
    assert "```csharp" in out
    assert "var x = a < b && c > d;" in out
    assert "Console.WriteLine(x);" in out


def test_tasks_links_images_jira():
    out = md()
    assert "- [x] Define endpoint" in out
    assert "- [ ] Key Vault access" in out
    assert "the architecture page" in out
    assert "[Jira: PLAT-42]" in out
    assert "[image: flow diagram]" in out


def test_expand_and_time():
    out = md()
    assert "**Details**" in out and "Hidden detail text." in out
    assert "2026-12-01" in out


def test_no_leftover_confluence_tags():
    out = md()
    assert "ac:" not in out and "ri:" not in out

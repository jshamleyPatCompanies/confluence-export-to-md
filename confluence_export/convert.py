"""Convert Confluence storage format (XHTML + ac:/ri: macros) to Markdown."""

from __future__ import annotations

import html
import re
from typing import Callable, Optional

from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify

UserResolver = Optional[Callable[[str], str]]

PANEL_MACROS = {
    "info": "Info",
    "note": "Note",
    "warning": "Warning",
    "tip": "Tip",
    "panel": "Note",
    "success": "Success",
    "error": "Error",
}
# Macros that add nothing useful as text.
DROP_MACROS = {"toc", "anchor", "children", "pagetree", "recently-updated",
               "contributors", "livesearch", "create-from-template", "space-details"}

_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def storage_to_markdown(storage_html: str, resolve_user: UserResolver = None) -> str:
    # html.parser doesn't reliably keep CDATA (used by code macros); escape it into text.
    text = _CDATA.sub(lambda m: html.escape(m.group(1)), storage_html or "")
    soup = BeautifulSoup(f"<div>{text}</div>", "html.parser")
    _preprocess(soup, resolve_user)
    md = markdownify(
        str(soup),
        heading_style="ATX",
        bullets="-",
        code_language_callback=lambda el: el.get("data-lang") or None,
    )
    return _tidy(md)


def _new(soup: BeautifulSoup, name: str, text: str | None = None, **attrs) -> Tag:
    t = soup.new_tag(name, attrs=attrs)
    if text is not None:
        t.string = text
    return t


def _param(macro: Tag, name: str) -> str | None:
    p = macro.find("ac:parameter", attrs={"ac:name": name})
    return p.get_text(strip=True) if p else None


def _preprocess(soup: BeautifulSoup, resolve_user: UserResolver) -> None:
    # Macros: process innermost first so nested macros are handled cleanly.
    macros = soup.find_all(["ac:structured-macro", "ac:macro"])
    for macro in reversed(macros):
        _convert_macro(soup, macro)

    for img in soup.find_all("ac:image"):
        att = img.find("ri:attachment")
        url = img.find("ri:url")
        alt = img.get("ac:alt") or (att.get("ri:filename") if att else None) or (url.get("ri:value") if url else "image")
        img.replace_with(f"[image: {alt}]")

    for link in soup.find_all("ac:link"):
        body = link.find(["ac:link-body", "ac:plain-text-link-body"])
        label = body.get_text(strip=True) if body else ""
        page = link.find("ri:page")
        user = link.find("ri:user")
        att = link.find("ri:attachment")
        if user is not None:
            acc = user.get("ri:account-id", "")
            name = resolve_user(acc) if (resolve_user and acc) else (label or "user")
            link.replace_with(f"@{name}")
        elif page is not None:
            link.replace_with(label or page.get("ri:content-title", ""))
        elif att is not None:
            link.replace_with(f"[attachment: {label or att.get('ri:filename', '')}]")
        else:
            link.replace_with(label)

    for tl in soup.find_all("ac:task-list"):
        ul = _new(soup, "ul")
        for task in tl.find_all("ac:task", recursive=False):
            status = task.find("ac:task-status")
            body = task.find("ac:task-body")
            box = "[x]" if status and status.get_text(strip=True) == "complete" else "[ ]"
            ul.append(_new(soup, "li", f"{box} {body.get_text(' ', strip=True) if body else ''}"))
        tl.replace_with(ul)

    for t in soup.find_all("time"):
        t.replace_with(t.get("datetime", t.get_text()))

    for e in soup.find_all(["ac:emoticon", "ac:placeholder", "ac:inline-comment-marker"]):
        if e.name == "ac:inline-comment-marker":
            e.unwrap()
        else:
            e.decompose()

    # Layout wrappers and any leftover ac:/ri: tags: keep their text content.
    for e in soup.find_all(lambda t: isinstance(t, Tag) and t.name.split(":")[0] in ("ac", "ri")):
        e.unwrap()

    # Table cells often wrap content in <p>; flatten so Markdown tables stay on one line.
    for cell in soup.find_all(["td", "th"]):
        for p in cell.find_all("p"):
            p.insert_after(" ")
            p.unwrap()
        for br in cell.find_all("br"):
            br.replace_with(" ")


def _convert_macro(soup: BeautifulSoup, macro: Tag) -> None:
    name = (macro.get("ac:name") or "").lower()
    rich = macro.find("ac:rich-text-body")
    plain = macro.find("ac:plain-text-body")

    if name in DROP_MACROS:
        macro.decompose()
        return

    if name in ("code", "noformat"):
        pre = _new(soup, "pre")
        code = _new(soup, "code", plain.get_text() if plain else "")
        lang = _param(macro, "language")
        if lang:
            pre["data-lang"] = lang  # markdownify passes the <pre> to the language callback
        pre.append(code)
        macro.replace_with(pre)
        return

    if name in PANEL_MACROS:
        title = _param(macro, "title")
        bq = _new(soup, "blockquote")
        label = _new(soup, "p")
        label.append(_new(soup, "strong", f"{PANEL_MACROS[name]}{': ' + title if title else ''}"))
        bq.append(label)
        if rich:
            for child in list(rich.contents):
                bq.append(child.extract())
        macro.replace_with(bq)
        return

    if name in ("expand", "details"):
        div = _new(soup, "div")
        title = _param(macro, "title")
        if title:
            p = _new(soup, "p")
            p.append(_new(soup, "strong", title))
            div.append(p)
        if rich:
            for child in list(rich.contents):
                div.append(child.extract())
        macro.replace_with(div)
        return

    if name == "status":
        macro.replace_with(f"[{(_param(macro, 'title') or '').upper()}]")
        return

    if name == "jira":
        key = _param(macro, "key")
        jql = _param(macro, "jqlQuery")
        macro.replace_with(f"[Jira: {key}]" if key else (f"[Jira query: {jql}]" if jql else "[Jira issues]"))
        return

    if name in ("include", "excerpt-include"):
        page = macro.find("ri:page")
        title = page.get("ri:content-title") if page else "another page"
        macro.replace_with(f"[Included from page: {title}]")
        return

    if name == "excerpt" and rich:
        rich.unwrap()
        macro.unwrap()
        return

    # Unknown macro: keep any body text, otherwise leave a marker.
    if rich:
        for p in macro.find_all("ac:parameter"):
            p.decompose()
        macro.unwrap()
    else:
        macro.replace_with(f"[{name} macro]" if name else "")


def _tidy(md: str) -> str:
    md = md.replace(" ", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"

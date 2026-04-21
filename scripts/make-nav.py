#!/usr/bin/env python3
"""Build modules/ROOT/nav.adoc from the extracted TOC.

Nav only lists distinct pages (i.e. skip in-page anchor-only entries).
Keeps nesting where a child lives in a different file.
"""

import json
import re
from pathlib import Path

ROOT = Path("/home/stefan/asterisk-buch")
tree = json.loads(Path("/tmp/asterisk-conv/toc.json").read_text(encoding="utf-8"))


def to_adoc(page: str) -> str:
    if page.endswith(".html"):
        return page[:-5] + ".adoc"
    return page


def fmt_label(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


lines: list[str] = []
seen_pages: set[str] = set()


def walk(entries, depth):
    marker = "*" * (depth + 1)
    for e in entries:
        page = to_adoc(e["page"])
        if page == "vorwort.adoc":
            page = "index.adoc"
        # Skip entries that only vary by anchor inside an already-emitted
        # page — nav should route to pages, not in-page sections.
        if e.get("anchor") and page in seen_pages:
            # Descend into its children (unlikely to matter here).
            continue
        if page in seen_pages and not e["children"]:
            continue
        label = fmt_label(e["title"])
        lines.append(f"{marker} xref:{page}[{label}]")
        seen_pages.add(page)
        if e["children"]:
            walk(e["children"], depth + 1)


preface = [e for e in tree if e["kind"] == "preface"]
chapters = [e for e in tree if e["kind"] == "chapter"]
glossary = [e for e in tree if e["kind"] == "glossary"]
appendix = [e for e in tree if e["kind"] == "appendix"]
indexes = [e for e in tree if e["kind"] == "index"]

# Preface
for e in preface:
    page = to_adoc(e["page"])
    if page == "vorwort.adoc":
        page = "index.adoc"
    lines.append(f"* xref:{page}[{fmt_label(e['title'])}]")
    seen_pages.add(page)

if chapters:
    lines.append("")
    lines.append(".Kapitel")
    walk(chapters, 0)

if glossary:
    lines.append("")
    lines.append(".Glossar")
    walk(glossary, 0)

if appendix:
    lines.append("")
    lines.append(".Anhang")
    walk(appendix, 0)

if indexes:
    lines.append("")
    lines.append(".Stichwortverzeichnis")
    walk(indexes, 0)

nav = "\n".join(lines) + "\n"
(ROOT / "modules" / "ROOT" / "nav.adoc").write_text(nav, encoding="utf-8")
print(f"Wrote nav.adoc with {len(lines)} lines, {len(seen_pages)} unique pages")

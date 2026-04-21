#!/usr/bin/env python3
"""Parse index.html and emit a structured TOC (JSON)."""
import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

SRC = Path("/home/stefan/asterisk-buch/index.html")
html = SRC.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

toc_div = soup.find("div", class_="toc")
if not toc_div:
    sys.exit("No .toc div found")
root_dl = toc_div.find("dl", recursive=False)


def clean_text(el):
    t = el.get_text(" ", strip=True)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^(\d+(\.\d+)*\.?|[A-Z]\.)\s*", "", t)
    t = t.replace("„ „", "„").replace("\" \"", "\"").replace("“ “", "“")
    t = re.sub(r"„\s+", "„", t)
    t = re.sub(r"\s+“", "“", t)
    return t.strip()


def walk_dl(dl, depth=0, acc=None):
    if acc is None:
        acc = []
    # Iterate dt/dd pairs by position so each dt gets only its immediately
    # following dd.
    children = [c for c in dl.children if getattr(c, "name", None) in ("dt", "dd")]
    i = 0
    while i < len(children):
        dt = children[i]
        if dt.name != "dt":
            i += 1
            continue
        span = dt.find("span", recursive=False)
        a = span.find("a") if span else None
        if not a or not a.get("href"):
            i += 1
            continue
        kind = span.get("class", [None])[0]
        href = a["href"]
        if href.startswith(("http", "#")):
            i += 1
            continue
        page, _, anchor = href.partition("#")
        title = clean_text(a)
        entry = {
            "kind": kind,
            "title": title,
            "page": page,
            "anchor": anchor or None,
            "depth": depth,
            "children": [],
        }
        dd = children[i + 1] if i + 1 < len(children) and children[i + 1].name == "dd" else None
        if dd:
            inner_dl = dd.find("dl", recursive=False)
            if inner_dl:
                walk_dl(inner_dl, depth + 1, entry["children"])
            i += 2
        else:
            i += 1
        acc.append(entry)
    return acc


tree = walk_dl(root_dl)
out = Path("/tmp/asterisk-conv/toc.json")
out.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {out}  ({len(tree)} top-level entries)")

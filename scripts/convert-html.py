#!/usr/bin/env python3
"""
Convert Das-Asterisk-Buch HTML pages (DocBook-style) into Antora AsciiDoc pages.

For every *.html in SRC, emit a corresponding *.adoc in DEST, stripping
site chrome (navbar, sidebar, ads, breadcrumbs, footer scripts) and
transforming the DocBook-flavoured HTML body into AsciiDoc.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag

SRC = Path("/home/stefan/asterisk-buch")
DEST = SRC / "modules" / "ROOT" / "pages"
DEST.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# small helpers
# -----------------------------------------------------------------------------

def adoc_escape_text(s: str) -> str:
    """Minimal escaping for AsciiDoc paragraph text."""
    if not s:
        return ""
    # Tabs and collapsing whitespace is done at the paragraph boundary.
    return s


def strip_classnum(title: str) -> str:
    """Strip the leading numeric/letter marker DocBook prepends to titles.

    Examples handled:
      'Kapitel 2. „Hello World"'          → '„Hello World"'
      'Anhang C. Applikationen im Dialplan' → 'Applikationen im Dialplan'
      'C.38. Dial()'                       → 'Dial()'
      '2.3. Hello-World im CLI aufrufen'   → 'Hello-World im CLI aufrufen'
    """
    title = re.sub(
        r"^(Kapitel\s+\d+\.\s*|Anhang\s+[A-Z]\.\s*|Teil\s+\w+\.\s*)", "", title
    ).strip()
    # Strip any combination of leading section markers, e.g. "C.38." or "2.3.1."
    title = re.sub(r"^((?:[A-Z]|\d+)(?:\.\d+)*\.\s*)+", "", title).strip()
    return title


def clean_title(el: Tag) -> str:
    """Extract a clean title string from a DocBook <h2 class=title> node."""
    t = inline_emit(el).strip()
    # Strip leading §/chapter/appendix marker.
    t = strip_classnum(t)
    # Remove stray quote decoration: „„Hello World"" → „Hello World"
    t = re.sub(r"\s+", " ", t).strip()
    return t


def href_to_xref(href: str) -> tuple[str, str | None]:
    """Map 'foo.html#bar' → ('foo.adoc', 'bar').  External / empty: (href, None)."""
    if not href:
        return ("", None)
    if href.startswith(("http://", "https://", "mailto:", "ftp://", "tel:")):
        return (href, None)
    if href.startswith("#"):
        return ("", href[1:])
    m = re.match(r"([^#?]+)(?:\?[^#]*)?(?:#(.*))?$", href)
    if not m:
        return (href, None)
    page, anchor = m.group(1), m.group(2)
    if page.endswith(".html"):
        page = page[:-5] + ".adoc"
    return (page, anchor)


# -----------------------------------------------------------------------------
# State threaded through emission
# -----------------------------------------------------------------------------

class Ctx:
    def __init__(self):
        self.footnotes: list[tuple[str, str]] = []   # (orig_id, text)
        self.footnote_seen_ids: dict[str, int] = {}  # orig_id → index in footnotes
        # Positional fallback: the order in which footnote <sup> references
        # appeared in the body, so we can pair them with id-less footnote
        # <div>s in the same document order.
        self.footnote_ref_order: list[str] = []


# -----------------------------------------------------------------------------
# Inline emission — anything that goes inside a paragraph or a list item.
# Returns a single line of AsciiDoc text (no trailing newline).
# -----------------------------------------------------------------------------

def inline_emit(node, ctx: Ctx | None = None) -> str:
    if ctx is None:
        ctx = Ctx()
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    classes = set(node.get("class") or [])

    # ------------------------------------------------------------------
    # Skip / transparent
    # ------------------------------------------------------------------
    if name in ("script", "style", "noscript"):
        return ""
    if "indexterm" in classes:
        return ""

    # ------------------------------------------------------------------
    # Recurse into children helpers
    # ------------------------------------------------------------------
    def kids() -> str:
        return "".join(inline_emit(c, ctx) for c in node.children)

    # ------------------------------------------------------------------
    # DocBook quote spans — strip the decorative double-wrapping
    #   <span class="quote">„<span class="quote">Hello</span>“</span>
    # becomes just: „Hello“
    # ------------------------------------------------------------------
    if "quote" in classes and name == "span":
        inner = kids()
        # Collapse nested „…“ if present.
        inner = re.sub(r"„\s*„", "„", inner)
        inner = re.sub(r"“\s*“", "“", inner)
        return inner

    # ------------------------------------------------------------------
    # Footnotes:  <sup>[<a class="footnote" href="#ftn.id">N</a>]</sup>
    # ------------------------------------------------------------------
    if name == "sup":
        a = node.find("a", class_="footnote")
        if a and a.get("href", "").startswith("#"):
            orig_id = a["href"][1:]  # e.g. "ftn.idp9329808"
            # Record order for positional fallback — some pages omit the
            # target id on the footnote div and rely on document order.
            if orig_id not in ctx.footnote_ref_order:
                ctx.footnote_ref_order.append(orig_id)
            return f"\x00FOOTREF:{orig_id}\x00"

    # ------------------------------------------------------------------
    # Code / emphasis / strong
    # ------------------------------------------------------------------
    if name == "code":
        txt = kids()
        # Strip leading/trailing whitespace; keep internal spaces.
        txt = txt.strip()
        if not txt:
            return ""
        # If the code span wraps a link/xref/mailto, don't wrap the
        # rendered link in backticks — AsciiDoc rejects that.
        if any(marker in txt for marker in ("xref:", "mailto:", "http://", "https://")):
            return txt
        # Avoid `` inside ``.
        if "`" in txt:
            return f"+{txt}+"
        return f"`{txt}`"

    if name in ("strong", "b"):
        txt = kids().strip()
        return f"*{txt}*" if txt else ""

    if name in ("em", "i"):
        txt = kids().strip()
        return f"_{txt}_" if txt else ""

    if name == "span":
        if "bold" in classes:
            # DocBook nests <strong> inside <span class="bold">;
            # emit the inner text as a single bold run.
            txt = "".join(
                kids_child if isinstance(c, NavigableString) else inline_emit(c, ctx).strip("*")
                for c, kids_child in ((c, str(c)) for c in node.children)
            )
            txt = txt.strip()
            return f"*{txt}*" if txt else ""
        if "emphasis" in classes:
            txt = "".join(
                kids_child if isinstance(c, NavigableString) else inline_emit(c, ctx).strip("_")
                for c, kids_child in ((c, str(c)) for c in node.children)
            ).strip()
            return f"_{txt}_" if txt else ""
        # Plain span — just emit children.
        return kids()

    # ------------------------------------------------------------------
    # Links / cross references
    # ------------------------------------------------------------------
    if name == "a":
        href = node.get("href", "")
        label = kids().strip()
        if not href:
            return label
        if "indexterm" in classes:
            return ""
        # Email
        if "email" in classes or href.startswith("mailto:"):
            addr = href[7:] if href.startswith("mailto:") else href
            return f"mailto:{addr}[{label or addr}]"
        # Same-page anchor
        if href.startswith("#"):
            anchor = href[1:]
            return f"<<{anchor},{label}>>" if label else f"<<{anchor}>>"
        # External
        if href.startswith(("http://", "https://", "ftp://")):
            safe = href
            if label and label != href:
                return f"{safe}[{label}]"
            return safe
        # Internal page link
        page, anchor = href_to_xref(href)
        if anchor:
            return f"xref:{page}#{anchor}[{label}]" if label else f"xref:{page}#{anchor}[]"
        return f"xref:{page}[{label}]" if label else f"xref:{page}[]"

    # ------------------------------------------------------------------
    # Line break
    # ------------------------------------------------------------------
    if name == "br":
        return " +\n"

    # ------------------------------------------------------------------
    # Image (inline)
    # ------------------------------------------------------------------
    if name == "img":
        src = node.get("src", "")
        alt = node.get("alt", "")
        fname = re.sub(r"^(?:\./)?bilder/", "", src)
        return f"image:{fname}[{alt}]"

    # ------------------------------------------------------------------
    # default: just emit children
    # ------------------------------------------------------------------
    return kids()


# -----------------------------------------------------------------------------
# Block emission — things that take one or more lines.
# Each block returns a string ending with a single newline; the caller
# appends a blank line between blocks.
# -----------------------------------------------------------------------------

def text_of(el: Tag, ctx: Ctx) -> str:
    """Emit inline content from an element, then collapse whitespace."""
    raw = "".join(inline_emit(c, ctx) for c in el.children)
    raw = raw.replace("\u00a0", " ")
    # Collapse runs of whitespace around newlines.
    raw = re.sub(r"[ \t]*\n[ \t]*", "\n", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    return raw.strip()


def emit_block(node, ctx: Ctx, depth: int = 0, list_depth: int = 0) -> str:
    """Emit AsciiDoc for a block-level node. Returns text with trailing \\n."""
    if isinstance(node, NavigableString):
        s = str(node).strip()
        if not s:
            return ""
        return s + "\n"
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    classes = set(node.get("class") or [])

    # ----- site chrome / noise: skip entirely -------------------------
    if name in ("script", "style", "noscript"):
        return ""
    if any(c in classes for c in (
        "navbar", "navbar-inner", "sidebar-nav", "breadcrumbs",
        "docnav", "footer", "nav-collapse", "span3"
    )):
        return ""
    if node.get("id") in (
        "adsense-small-rectangle",
    ):
        return ""

    # ----- titlepage wrapper: produced by docbook, already rendered by
    #       the top-level page emitter ------------------------------------
    if "titlepage" in classes:
        return ""

    # ----- paragraph ---------------------------------------------------
    if "para" in classes or name == "p":
        # A <div class="para"> can contain inner <pre>, lists, notes etc.
        # Emit mixed content: split into runs of inline vs block.
        return emit_mixed(node, ctx, depth, list_depth)

    # ----- section -----------------------------------------------------
    if "section" in classes and name == "div":
        return emit_section(node, ctx, depth)

    # ----- preformatted blocks ----------------------------------------
    if name == "pre":
        return emit_pre(node, classes)

    # ----- admonitions -------------------------------------------------
    for kind in ("note", "tip", "warning", "important", "caution"):
        if kind in classes and name == "div":
            return emit_admon(node, kind, ctx, depth, list_depth)

    # ----- variable list (<dl> labeled list) --------------------------
    if "variablelist" in classes:
        dl = node.find("dl", recursive=False)
        if dl is not None:
            return emit_dl(dl, ctx, list_depth)

    # ----- itemized / ordered list wrappers ---------------------------
    if "itemizedlist" in classes:
        ul = node.find("ul", recursive=False)
        if ul is not None:
            return emit_ul(ul, ctx, list_depth)
    if "orderedlist" in classes:
        ol = node.find("ol", recursive=False)
        if ol is not None:
            return emit_ol(ol, ctx, list_depth)

    # ----- bare lists --------------------------------------------------
    if name == "ul":
        return emit_ul(node, ctx, list_depth)
    if name == "ol":
        return emit_ol(node, ctx, list_depth)
    if name == "dl":
        return emit_dl(node, ctx, list_depth)

    # ----- tables ------------------------------------------------------
    if name == "table" or "table" in classes or "informaltable" in classes:
        # Find the actual table element.
        t = node if name == "table" else node.find("table")
        if t is not None:
            return emit_table(t, ctx)

    # ----- blockquote --------------------------------------------------
    if name == "blockquote":
        body = "".join(emit_block(c, ctx, depth, list_depth) for c in node.children)
        return "[quote]\n____\n" + body.strip() + "\n____\n"

    # ----- figure / mediaobject ---------------------------------------
    if "mediaobject" in classes or "figure" in classes or name == "figure":
        img = node.find("img")
        if img is not None:
            src = img.get("src", "")
            alt = img.get("alt", "")
            fname = re.sub(r"^(?:\./)?bilder/", "", src)
            cap = node.find(class_="title") or node.find("figcaption")
            title = clean_title(cap) if cap else ""
            out = []
            if title:
                out.append(f".{title}")
            out.append(f"image::{fname}[{alt}]")
            return "\n".join(out) + "\n"

    # ----- horizontal rule --------------------------------------------
    if name == "hr":
        return "'''\n"

    # ----- formal paragraph: <div class="formalpara"><h5>Title</h5>…text…</div>
    if "formalpara" in classes and name == "div":
        h = None
        for c in node.children:
            if isinstance(c, Tag) and c.name and re.match(r"^h[2-6]$", c.name):
                h = c
                break
        title = clean_title(h) if h is not None else ""
        rest_children = [c for c in node.children if c is not h]
        # Emit the rest as a single paragraph of inline content so nested
        # <sup> footnote refs resolve correctly.
        paragraph = "".join(inline_emit(c, ctx) for c in rest_children)
        paragraph = re.sub(r"[ \t]*\n[ \t]*", "\n", paragraph)
        paragraph = re.sub(r"[ \t]+", " ", paragraph).strip()
        lines = []
        if title:
            lines.append(f".{title}")
        if paragraph:
            lines.append(paragraph)
        return ("\n".join(lines) + "\n") if lines else ""

    # ----- generic containers ------------------------------------------
    if name in ("div", "span", "section", "article", "main"):
        # Recurse through children as blocks.
        out = []
        for c in node.children:
            s = emit_block(c, ctx, depth, list_depth)
            if s:
                out.append(s)
        return "\n\n".join(x.strip("\n") for x in out if x.strip()) + ("\n" if out else "")

    # ----- headings we hit directly (rare — usually inside titlepage)
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        title = clean_title(node)
        level = int(name[1])
        return "=" * level + " " + title + "\n"

    # ----- fallback: treat as inline → paragraph ----------------------
    # Call inline_emit on the node itself so tag-level handlers (sup → footnote
    # placeholder, code → backticks, quote span stripping, …) fire. Using
    # text_of here would iterate children and skip the handler for the node.
    s = inline_emit(node, ctx)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s + "\n" if s else ""


def emit_mixed(node: Tag, ctx: Ctx, depth: int, list_depth: int) -> str:
    """
    Emit a <div class='para'> that may contain both inline content and
    block-level children (nested notes, <pre>, lists, etc.). Walk the
    children; flush accumulated inline content as a paragraph before
    each block-level child.
    """
    out_parts: list[str] = []
    buf: list[str] = []

    def flush_para():
        if not buf:
            return
        raw = "".join(buf)
        raw = raw.replace("\u00a0", " ")
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n[ \t]+", "\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        raw = raw.strip()
        if raw:
            out_parts.append(raw + "\n")
        buf.clear()

    for c in node.children:
        if isinstance(c, NavigableString):
            buf.append(str(c))
            continue
        if not isinstance(c, Tag):
            continue
        cname = c.name.lower()
        cclasses = set(c.get("class") or [])
        is_block = (
            cname == "pre"
            or "para" in cclasses
            or "section" in cclasses
            or cname in ("ul", "ol", "dl", "table", "hr", "blockquote")
            or "variablelist" in cclasses
            or "itemizedlist" in cclasses
            or "orderedlist" in cclasses
            or "informaltable" in cclasses
            or "mediaobject" in cclasses
            or "figure" in cclasses
            or any(k in cclasses for k in ("note", "tip", "warning", "important", "caution"))
        )
        if is_block:
            flush_para()
            s = emit_block(c, ctx, depth, list_depth)
            if s:
                out_parts.append(s)
        else:
            buf.append(inline_emit(c, ctx))

    flush_para()
    # Blocks separated by a blank line; each part's inner newlines preserved.
    return "\n\n".join(p.strip("\n") for p in out_parts if p.strip()) + ("\n" if out_parts else "")


def emit_pre(node: Tag, classes: set[str]) -> str:
    """Preformatted block → source listing."""
    raw = node.get_text()
    raw = raw.rstrip("\n")
    raw = raw.replace("\xa0", " ")

    lang = ""
    if "screen" in classes:
        lang = "shell"

    head = f"[source{',' + lang if lang else ''}]\n----"
    # Leading blank line ensures the block detaches from a preceding paragraph,
    # so AsciiDoc doesn't treat `[source]` as a block title of the paragraph.
    return f"\n{head}\n{raw}\n----\n\n"


def emit_admon(node: Tag, kind: str, ctx: Ctx, depth: int, list_depth: int) -> str:
    """note/tip/warning/important → AsciiDoc admonition block."""
    label = {
        "note": "NOTE",
        "tip": "TIP",
        "warning": "WARNING",
        "important": "IMPORTANT",
        "caution": "CAUTION",
    }[kind]
    # Skip the <h2> label produced by DocBook.
    parts = []
    for c in node.children:
        if isinstance(c, Tag) and c.name and c.name.lower() in ("h1", "h2", "h3", "h4"):
            continue
        s = emit_block(c, ctx, depth, list_depth)
        if s:
            parts.append(s)
    body = "\n".join(p.rstrip("\n") for p in parts).strip()
    return f"\n[{label}]\n====\n{body}\n====\n\n"


def emit_ul(node: Tag, ctx: Ctx, list_depth: int) -> str:
    marker = "*" * (list_depth + 1)
    return emit_list(node, ctx, marker, list_depth)


def emit_ol(node: Tag, ctx: Ctx, list_depth: int) -> str:
    marker = "." * (list_depth + 1)
    return emit_list(node, ctx, marker, list_depth)


def emit_list(node: Tag, ctx: Ctx, marker: str, list_depth: int) -> str:
    out = []
    for li in node.find_all("li", recursive=False):
        first_inline, blocks = split_li(li, ctx, list_depth)
        first_inline = first_inline.strip()
        out.append(f"{marker} {first_inline}")
        for b in blocks:
            b = b.strip("\n")
            if not b:
                continue
            out.append("+")
            out.append(b)
    # Blank line before and after the list so it detaches from surrounding prose.
    return "\n" + "\n".join(out) + "\n\n"


def split_li(li: Tag, ctx: Ctx, list_depth: int) -> tuple[str, list[str]]:
    """Return (first inline paragraph text, [further block strings]).

    The first <div class="para"> (or inline run before any block) becomes
    the leading inline text; every subsequent <div class="para"> becomes
    a continuation block that the caller will render with a `+` joiner.
    """
    inline_buf: list[str] = []
    blocks: list[str] = []
    seen_first_para = False
    started_blocks = False

    for c in li.children:
        if isinstance(c, NavigableString):
            if started_blocks:
                s = str(c).strip()
                if s:
                    blocks.append(s + "\n")
            else:
                inline_buf.append(str(c))
            continue
        if not isinstance(c, Tag):
            continue
        cname = c.name.lower()
        cclasses = set(c.get("class") or [])

        is_block = (
            cname == "pre"
            or cname in ("ul", "ol", "dl", "table", "hr", "blockquote")
            or "variablelist" in cclasses
            or "itemizedlist" in cclasses
            or "orderedlist" in cclasses
            or "informaltable" in cclasses
            or "mediaobject" in cclasses
            or any(k in cclasses for k in ("note", "tip", "warning", "important", "caution"))
        )

        if "para" in cclasses:
            # Render the para as mixed content so nested blocks (variablelists,
            # <pre>, admonitions) are broken out instead of being flattened.
            rendered = emit_mixed(c, ctx, 0, list_depth + 1).strip("\n")
            # Split the rendered para into a lead line and any follow-on blocks.
            split = rendered.split("\n\n", 1)
            lead = split[0].strip()
            rest = split[1].strip() if len(split) > 1 else ""
            if not seen_first_para and not started_blocks and not blocks:
                inline_buf.append(lead)
                if rest:
                    blocks.append(rest)
                    started_blocks = True
                seen_first_para = True
            else:
                if lead:
                    blocks.append(lead)
                if rest:
                    blocks.append(rest)
                started_blocks = True
            continue
        if is_block:
            started_blocks = True
            blocks.append(emit_block(c, ctx, 0, list_depth + 1))
            continue
        # inline tag
        if started_blocks:
            blocks.append(inline_emit(c, ctx))
        else:
            inline_buf.append(inline_emit(c, ctx))

    raw = "".join(inline_buf)
    raw = raw.replace("\u00a0", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw, blocks


def inline_emit_mixed(node: Tag, ctx: Ctx) -> str:
    """Inline-emit a para but collapse to single line of text."""
    parts = []
    for c in node.children:
        parts.append(inline_emit(c, ctx))
    s = "".join(parts)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def emit_dl(dl: Tag, ctx: Ctx, list_depth: int) -> str:
    out = []
    term_marker = ";" * (list_depth + 1) + ":"  # heuristic; not standard
    # AsciiDoc's labeled list uses `::` regardless of nesting; use `::` for
    # simplicity (Antora styles them the same).
    term_marker = "::"
    dts = dl.find_all("dt", recursive=False)
    for dt in dts:
        term = inline_emit_mixed(dt, ctx)
        dd = dt.find_next_sibling("dd")
        desc_text = ""
        extra_blocks: list[str] = []
        if dd is not None:
            # Split dd content similarly to list items.
            children = list(dd.children)
            # If the first child is a <div class="para">, treat it as the
            # description line; everything else is a block.
            first_inline, blocks = split_li(dd, ctx, list_depth)
            desc_text = first_inline
            extra_blocks = blocks
        out.append(f"{term}{term_marker} {desc_text}".rstrip())
        for b in extra_blocks:
            b = b.strip("\n")
            if not b:
                continue
            out.append("+")
            out.append(b)
    return "\n" + "\n".join(out) + "\n\n"


def emit_table(t: Tag, ctx: Ctx) -> str:
    """Emit a <table> as an AsciiDoc table."""
    rows = []
    thead = t.find("thead")
    has_header = thead is not None
    if has_header:
        header_cells = []
        for tr in thead.find_all("tr"):
            for th in tr.find_all(["th", "td"]):
                header_cells.append(inline_emit_mixed(th, ctx))
        rows.append(header_cells)

    body_trs = []
    tbody = t.find("tbody")
    if tbody:
        body_trs = tbody.find_all("tr")
    else:
        body_trs = [tr for tr in t.find_all("tr") if not (has_header and tr.find_parent("thead"))]

    for tr in body_trs:
        cells = []
        for td in tr.find_all(["td", "th"]):
            cells.append(inline_emit_mixed(td, ctx))
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    ncols = max(len(r) for r in rows)
    lines = [f"[cols=\"{ncols}*\"]", "|==="]
    if has_header and rows:
        # header row on one line
        lines.append("| " + " | ".join(rows[0]))
        lines.append("")
        body = rows[1:]
    else:
        body = rows
    for r in body:
        # pad row to ncols
        while len(r) < ncols:
            r.append("")
        lines.append("| " + " | ".join(c.replace("\n", " ") for c in r))
    lines.append("|===")
    return "\n".join(lines) + "\n"


def emit_section(node: Tag, ctx: Ctx, depth: int) -> str:
    """A <div class='section'> with a nested titlepage + body."""
    # Pull the <hN> under titlepage → the section title.
    title_h = None
    tp = node.find("div", class_="titlepage", recursive=False)
    if tp is not None:
        for h in tp.find_all(re.compile(r"^h[2-6]$")):
            title_h = h
            break
    anchor = node.get("id") or (title_h.get("id") if title_h else None)
    title = clean_title(title_h) if title_h else ""

    # Level: depth=0 is the page's top-level section. But the outer page
    # title is already rendered as `= Title`, so the first nested section
    # becomes `==`.
    level = depth + 2

    out = [""]  # blank line before the heading so it stands alone
    if anchor:
        out.append(f"[[{anchor}]]")
    marker = "=" * min(level, 6)
    if title:
        out.append(f"{marker} {title}")
    out.append("")  # blank line after heading

    # Body children: everything except titlepage
    body_parts = []
    for c in node.children:
        if isinstance(c, Tag) and "titlepage" in set(c.get("class") or []):
            continue
        s = emit_block(c, ctx, depth + 1, 0)
        if s and s.strip():
            body_parts.append(s.strip("\n"))

    header = "\n".join(out)
    body = "\n\n".join(body_parts)
    # A blank line between the heading and the body so paragraphs don't
    # get absorbed as the heading's trailing text.
    sep = "\n" if body else ""
    return header + sep + body + "\n"


# -----------------------------------------------------------------------------
# Footnote collection
# -----------------------------------------------------------------------------

def collect_footnotes(content: Tag, ctx: Ctx):
    """Find footnote <div>s and populate ctx.footnotes.

    DocBook emits footnote bodies in a few shapes:
      1. <div class="footnotes"><div class="footnote"><p><sup>[N]</sup>…</p></div>…
         with each footnote carrying an <a id="ftn.id"> anchor.
      2. Same wrapper, but no anchor id — resolved by document order.
      3. Table footnotes: <td>…<div class="footnote">…</div></td> — the
         footnote body hangs off the cell rather than a dedicated wrapper.
    """
    anchored: list[tuple[str, str]] = []
    unanchored: list[str] = []
    # Collect every .footnote div in the content, wherever it sits.
    for div in content.find_all("div", class_="footnote"):
        a = div.find("a", id=re.compile(r"^ftn\."))
        orig = a["id"] if a and a.has_attr("id") else None
        body_el = div.find("p") or div.find("div", class_="para") or div
        for sup in body_el.find_all("sup"):
            sup.decompose()
        text = inline_emit_mixed(body_el, ctx)
        if orig:
            anchored.append((orig, text))
        else:
            unanchored.append(text)

    for orig, text in anchored:
        if orig in ctx.footnote_seen_ids:
            continue
        ctx.footnotes.append((orig, text))
        ctx.footnote_seen_ids[orig] = len(ctx.footnotes) - 1
    ctx._unanchored_fn_texts = unanchored

    # Remove all footnote divs and the outer .footnotes wrapper from the
    # tree so the body walker doesn't re-emit them as prose / table cell
    # content. (The .footnotes wrapper is skipped at the page level, but
    # stray footnote divs attached to <td>s need explicit removal.)
    for div in content.find_all("div", class_="footnote"):
        div.decompose()
    for wrap in content.find_all("div", class_="footnotes"):
        wrap.decompose()


def resolve_footnote_placeholders(s: str, ctx: Ctx) -> str:
    """Replace \\x00FOOTREF:id\\x00 markers with footnote:[text]."""
    # Pair any id-less footnote texts with the body refs in document order.
    unanchored = getattr(ctx, "_unanchored_fn_texts", [])
    if unanchored:
        # Walk ref order; fill ids that didn't match an anchor.
        unmatched_refs = [r for r in ctx.footnote_ref_order if r not in ctx.footnote_seen_ids]
        for ref, text in zip(unmatched_refs, unanchored):
            ctx.footnotes.append((ref, text))
            ctx.footnote_seen_ids[ref] = len(ctx.footnotes) - 1

    def sub(m):
        orig = m.group(1)
        idx = ctx.footnote_seen_ids.get(orig)
        if idx is None:
            return ""
        text = ctx.footnotes[idx][1]
        text = text.replace("]", "\\]")
        return f"footnote:[{text}]"
    return re.sub(r"\x00FOOTREF:([^\x00]+)\x00", sub, s)


# -----------------------------------------------------------------------------
# Per-page driver
# -----------------------------------------------------------------------------

def find_content(soup: BeautifulSoup) -> Tag | None:
    """Locate the primary content container.

    DocBook emits the page body as a top-level <div class="preface|chapter|
    section|appendix|glossary|index|part">. Pick the outermost — i.e. the
    first one in document order for the best-matching class — regardless
    of whether it has an id (id-less outer sections do occur, e.g. the
    auto-generated ch20s*.html split-pages).
    """
    # Strip site chrome before searching so we can't accidentally latch
    # onto a stray .section inside navigation markup.
    for el in soup.select(
        ".navbar, .sidebar-nav, .breadcrumbs, .docnav, .footer, "
        "#adsense-small-rectangle"
    ):
        el.decompose()
    candidates = ["preface", "chapter", "appendix", "glossary", "index", "part", "book", "section"]
    for klass in candidates:
        el = soup.find("div", class_=klass)
        if el is not None:
            return el
    return soup.body


def render_toc_block(content: Tag, current_page: str) -> str:
    """For chapter hub pages, render the inner .toc as an AsciiDoc bullet list."""
    toc = content.find("div", class_="toc", recursive=False)
    if toc is None:
        return ""
    dl = toc.find("dl", recursive=False)
    if dl is None:
        return ""
    out: list[str] = []

    def walk(dl: Tag, level: int):
        marker = "*" * (level + 1)
        # Iterate the dl's children in order so each dt is paired with the
        # *immediately* following dd (if any), not some later sibling.
        children = [c for c in dl.children if isinstance(c, Tag) and c.name in ("dt", "dd")]
        i = 0
        while i < len(children):
            dt = children[i]
            if dt.name != "dt":
                i += 1
                continue
            a = dt.find("a")
            if not a:
                i += 1
                continue
            href = a.get("href", "")
            label = inline_emit_mixed(a, Ctx())
            label = strip_classnum(label)
            if not href:
                out.append(f"{marker} {label}")
            else:
                page, anchor = href_to_xref(href)
                if anchor:
                    out.append(f"{marker} xref:{page}#{anchor}[{label}]")
                else:
                    out.append(f"{marker} xref:{page}[{label}]")
            dd = children[i + 1] if i + 1 < len(children) and children[i + 1].name == "dd" else None
            if dd:
                inner = dd.find("dl", recursive=False)
                if inner:
                    walk(inner, level + 1)
                i += 2
            else:
                i += 1

    walk(dl, 0)
    return "\n".join(out) + "\n"


def convert_page(html_path: Path) -> str:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    content = find_content(soup)
    if content is None:
        return ""

    ctx = Ctx()
    collect_footnotes(content, ctx)

    # Title
    tp = content.find("div", class_="titlepage")
    title_h = None
    subtitle_h = None
    if tp is not None:
        for h in tp.find_all(re.compile(r"^h[1-6]$")):
            cls = set(h.get("class") or [])
            if "subtitle" in cls and subtitle_h is None:
                subtitle_h = h
            elif "title" in cls and title_h is None:
                title_h = h
    page_title = clean_title(title_h) if title_h else html_path.stem
    page_subtitle = text_of(subtitle_h, Ctx()) if subtitle_h is not None else ""
    page_anchor = content.get("id")

    # Top-of-page attributes — the preface is specifically index.adoc.
    is_preface = "preface" in set(content.get("class") or []) or html_path.stem == "vorwort"

    out: list[str] = []
    if page_anchor:
        out.append(f"[[{page_anchor}]]")
    out.append(f"= {page_title}")
    if is_preface:
        out.append(":page-notoc: true")
    out.append("")
    if page_subtitle:
        # Preserve the DocBook subtitle as an italicised sub-heading line.
        out.append(f"_{page_subtitle}_")
        out.append("")

    # Special case: chapter-hub pages (their content is only a titlepage + a
    # .toc listing their child sections). Emit a short lead paragraph (if any)
    # plus a bulleted xref list.
    is_chapter_hub = (
        "chapter" in set(content.get("class") or [])
        and content.find("div", class_="toc", recursive=False) is not None
    )
    body_parts: list[str] = []
    # Walk ALL children in document order; replace the inner <div class="toc">
    # (if any) with a rendered bullet-list of xrefs at its in-situ position.
    # Earlier versions stopped at the first .toc and lost any prose that
    # appears after it (e.g. warteschleifen.html's tip + code examples).
    toc_rendered_once = False
    for c in content.children:
        if isinstance(c, Tag):
            cls = set(c.get("class") or [])
            if "titlepage" in cls:
                continue
            if "footnotes" in cls:
                continue
            if c.get("id") == "adsense-small-rectangle":
                continue
            if "toc" in cls:
                if is_chapter_hub and not toc_rendered_once:
                    toc_text = render_toc_block(content, html_path.name)
                    if toc_text.strip():
                        # A short lead-in keeps the bulleted TOC from
                        # appearing unannounced on the page.
                        body_parts.append("In diesem Kapitel:")
                        body_parts.append(toc_text.strip("\n"))
                    toc_rendered_once = True
                continue
            s = emit_block(c, ctx, 0, 0)
            if s and s.strip():
                body_parts.append(s.strip("\n"))
        elif isinstance(c, NavigableString):
            s = str(c).strip()
            if s:
                body_parts.append(s)

    header = "\n".join(p for p in out if p != "")
    body = "\n\n".join(body_parts)
    text = header + "\n\n" + body
    text = resolve_footnote_placeholders(text, ctx)

    # Final cleanups
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.replace("\u00a0", " ")
    # Collapse multiple spaces that aren't inside a source block.
    # We do a safe pass by splitting on source blocks.
    return protect_source_blocks(text) + "\n"


def protect_source_blocks(text: str) -> str:
    """Collapse excessive whitespace only outside of ---- fenced blocks."""
    parts = re.split(r"(\n----\n(?:.|\n)*?\n----\n)", text)
    rebuilt = []
    for p in parts:
        if p.startswith("\n----\n"):
            rebuilt.append(p)
        else:
            q = re.sub(r"[ \t]{2,}", " ", p)
            q = re.sub(r"[ \t]+\n", "\n", q)
            rebuilt.append(q)
    return "".join(rebuilt)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main():
    html_files = sorted(SRC.glob("*.html"))
    n = len(html_files)
    errors = []
    written = 0
    for i, f in enumerate(html_files, 1):
        try:
            text = convert_page(f)
            # vorwort.html → index.adoc (preface becomes site entry point)
            stem = f.stem
            if stem == "index":
                # The original index is the ToC page — we don't need it;
                # its role is now served by nav.adoc, and vorwort becomes index.
                continue
            if stem == "vorwort":
                target = DEST / "index.adoc"
            else:
                target = DEST / (stem + ".adoc")
            target.write_text(text, encoding="utf-8")
            written += 1
        except Exception as e:  # pragma: no cover
            errors.append((f.name, repr(e)))
    print(f"Converted {written}/{n} pages.  Errors: {len(errors)}")
    for name, err in errors[:20]:
        print("  -", name, err)


if __name__ == "__main__":
    main()

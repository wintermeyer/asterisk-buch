#!/usr/bin/env python3
"""Compare word counts: HTML content vs converted AsciiDoc.

For each HTML page, extract the main content (stripping navbar/sidebar/ads/
breadcrumb/footer/scripts) and count its text words, then compare with the
word count of the generated .adoc. Significant drops indicate content loss.
"""

from __future__ import annotations
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

SRC = Path("/home/stefan/asterisk-buch")
DEST = SRC / "modules" / "ROOT" / "pages"


def extract_body_text(html_path: Path) -> str:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    # Drop chrome
    for el in soup.select(
        ".navbar, .sidebar-nav, .breadcrumbs, .docnav, .footer, "
        "#adsense-small-rectangle, script, style, noscript"
    ):
        el.decompose()
    # Pick primary content
    for cls in ("preface", "chapter", "section", "appendix", "glossary", "index", "part"):
        el = soup.find("div", class_=cls)
        if el is not None:
            return el.get_text(" ", strip=True)
    if soup.body:
        return soup.body.get_text(" ", strip=True)
    return ""


def strip_adoc(text: str) -> str:
    # Remove anchors [[..]], block attributes [source,…], fenced code
    # markers, nav markers, admonition block delimiters — to leave prose
    # + preserved code lines for a like-for-like comparison.
    text = re.sub(r"^\[\[.*?\]\]\s*$", "", text, flags=re.M)
    text = re.sub(r"^:[a-zA-Z0-9_-]+:.*$", "", text, flags=re.M)  # page attribs
    text = re.sub(r"^\[.*?\]\s*$", "", text, flags=re.M)          # block attrs
    text = re.sub(r"^[=]{1,6}\s+", "", text, flags=re.M)          # heading markers
    text = re.sub(r"^[*\.]+\s+", "", text, flags=re.M)            # list markers
    text = re.sub(r"^-{4,}\s*$", "", text, flags=re.M)            # ---- fences
    text = re.sub(r"^={4,}\s*$", "", text, flags=re.M)            # ==== admon fences
    text = re.sub(r"xref:([^\[]+)\[([^\]]*)\]", r"\2", text)       # xref label only
    text = re.sub(r"mailto:([^\[]+)\[([^\]]*)\]", r"\2", text)     # mailto label only
    text = re.sub(r"image::?([^\[]+)\[([^\]]*)\]", r"", text)      # drop images
    text = re.sub(r"footnote:\[(.*?)\]", r"\1", text)              # inline footnote text
    text = re.sub(r"[`+_*]", "", text)                              # emphasis markers
    return text


def count_words(s: str) -> int:
    return len(re.findall(r"\S+", s))


def main(threshold: float = 0.60):
    rows: list[tuple[str, int, int, float]] = []
    for html in sorted(SRC.glob("*.html")):
        stem = html.stem
        if stem == "index":
            continue
        adoc_name = "index.adoc" if stem == "vorwort" else stem + ".adoc"
        adoc = DEST / adoc_name
        if not adoc.exists():
            rows.append((html.name, 0, 0, 0.0))
            continue
        html_text = extract_body_text(html)
        adoc_text = strip_adoc(adoc.read_text(encoding="utf-8"))
        hw = count_words(html_text)
        aw = count_words(adoc_text)
        ratio = (aw / hw) if hw else 1.0
        rows.append((html.name, hw, aw, ratio))

    rows.sort(key=lambda r: r[3])
    print("=== worst coverage (ratio of adoc words / html words) ===")
    print(f"{'page':<60} {'html':>6} {'adoc':>6} {'ratio':>6}")
    for name, hw, aw, ratio in rows[:30]:
        print(f"{name:<60} {hw:>6} {aw:>6} {ratio:>6.2f}")
    print()
    low = [r for r in rows if r[3] < threshold and r[1] > 20]
    print(f"Pages with ratio < {threshold} and >20 html words: {len(low)}")
    total_html = sum(r[1] for r in rows)
    total_adoc = sum(r[2] for r in rows)
    print(f"Totals:  html={total_html}  adoc={total_adoc}  ratio={total_adoc/total_html:.3f}")


if __name__ == "__main__":
    main(threshold=float(sys.argv[1]) if len(sys.argv) > 1 else 0.80)

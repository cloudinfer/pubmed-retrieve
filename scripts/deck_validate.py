"""
Phase 5 layout validator for pubmed-retrieve decks.

Enforces the hard rules in references/deck-theme.md (section 10) and the
structural contracts in references/deck-layouts.md.

Exit code 0 = no P0 issues (deliverable). Exit code 1 = P0 found.

Usage:
    python deck_validate.py output/deck.html
    python deck_validate.py output/deck.html --strict   # P1 also fails
"""

from __future__ import annotations

import argparse
import re
import sys

SCHEMA_LAYOUTS = {
    "M01", "M02", "M03", "M04", "M05", "M06",
    "M07", "M08", "M09", "M10", "M11", "M12",
    "M13", "M14", "M15", "M16", "M17", "M18",
    "M19", "M20",
}
DARK_LAYOUTS = {"M01", "M12"}

PALETTE = {
    "0A1B2E",  # --ink
    "4A5C72",  # --ink-2
    "8593A3",  # --ink-3
    "0A3D7C",  # --anchor
    "2E6BA8",  # --anchor-2
    "8FB3D9",  # --anchor-3
    "EEF3F9",  # --wash
    "CBD7E4",  # --hairline
    "FFFFFF",  # --paper
    "B01E28",  # --alert
    "DFE5EC",  # --chrome-bg
    "A9B6C6",  # --chrome-idle
}
HEX_RE = re.compile(r"#([0-9A-Fa-f]{3,8})\b")
DECL_RE = re.compile(r"([-a-zA-Z]+)\s*:\s*([^;{}\"']+)")
SLIDE_RE = re.compile(r"<section\b[^>]*>.*?</section>", re.DOTALL)
STYLE_ATTR_RE = re.compile(r'style="([^"]*)"')
PRESENTATION_ATTR_RE = re.compile(r'(?:fill|stroke)="([^"]*)"')
STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL)

MIN_FONT_PX = 13.0
BAD_WEIGHTS = {"600", "700", "800", "900"}
ALERT_HEX = "B01E28"


def normalize_hex(raw: str) -> str:
    h = raw.upper()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return h


class Report:
    def __init__(self):
        self.p0: list[str] = []
        self.p1: list[str] = []
        self.p2: list[str] = []

    def add(self, level: str, msg: str) -> None:
        getattr(self, level).append(msg)


def collect_declarations(css_text: str):
    """Yield (property, value) pairs from CSS text or a style attribute."""
    for prop, value in DECL_RE.findall(css_text):
        yield prop.strip().lower(), value.strip()


def check_colors(text: str, where: str, rep: Report) -> None:
    for raw in HEX_RE.findall(text):
        if normalize_hex(raw) not in PALETTE:
            rep.add("p0", f"F01 调色板外颜色 #{raw}（{where}）")


def check_declarations(css_text: str, where: str, rep: Report) -> None:
    for prop, value in collect_declarations(css_text):
        low = value.lower()
        if prop == "border-radius":
            for num in re.findall(r"([\d.]+)\s*(px|em|rem|%)?", low):
                try:
                    if float(num[0]) > 0:
                        rep.add("p0", f"F02 出现非零圆角 border-radius:{value}（{where}）")
                        break
                except ValueError:
                    pass
        elif prop in ("box-shadow", "text-shadow"):
            if low not in ("none", ""):
                rep.add("p0", f"F03 出现阴影 {prop}:{value}（{where}）")
        elif "gradient" in low:
            rep.add("p0", f"F04 出现渐变 {prop}:{value}（{where}）")
        elif prop == "font-size":
            m = re.match(r"^(\d+(?:\.\d+)?)px$", low)
            if m:
                if float(m.group(1)) < MIN_FONT_PX:
                    rep.add("p0", f"F05 字号 {value} 低于 {MIN_FONT_PX:g}px（{where}）")
            elif low.endswith(("em", "rem", "%")):
                rep.add("p2", f"F05 字号使用相对单位 {value}，无法校验下限（{where}）")
            elif not re.match(r"^(large|medium|small|x-|xx-|calc|var)", low):
                rep.add("p2", f"F05 字号为关键字 {value}，无法校验下限（{where}）")
        elif prop == "font-weight":
            if low in BAD_WEIGHTS:
                rep.add("p1", f"F06 使用禁用字重 font-weight:{value}（{where}）")
        elif prop == "font-style" and low in ("italic", "oblique"):
            rep.add("p1", f"F06 使用斜体 font-style:{value}（{where}）")
        elif prop == "text-align" and low == "center":
            rep.add("p1", f"F07 出现 text-align:center（{where}）")


def has_class(block: str, name: str) -> bool:
    """True if any element in the block carries the given class token."""
    return bool(re.search(rf'class="[^"]*\b{re.escape(name)}\b[^"]*"', block))


def check_structure(doc: str, rep: Report) -> int:
    slides = SLIDE_RE.findall(doc)
    if not slides:
        rep.add("p0", "未找到任何 <section class=\"slide\"> 页面")
        return 0

    for idx, block in enumerate(slides, start=1):
        tag = re.match(r"<section\b[^>]*>", block).group(0)
        layout_m = re.search(r'data-layout="([^"]*)"', tag)
        layout = layout_m.group(1) if layout_m else ""
        where = f"第 {idx} 页"
        if layout not in SCHEMA_LAYOUTS:
            rep.add("p0", f"F10 未知版式 data-layout=\"{layout}\"（{where}）")
            continue

        dark = re.search(r'data-dark="1"', tag) is not None
        if layout in DARK_LAYOUTS and not dark:
            rep.add("p1", f"F13 {layout} 应为深色底但 data-dark 不为 1（{where}）")
        if layout not in DARK_LAYOUTS and dark:
            rep.add("p1", f"F13 {layout} 为白底版式却设置了深色底（{where}）")

        if layout not in ("M01", "M12"):
            for cls in ("head", "pageno", "foot"):
                if not has_class(block, cls):
                    rep.add("p1", f"F09 {layout} 缺少 .{cls}（{where}）")
            rule_count = len(re.findall(r'class="[^"]*\brule\b[^"]*"', block))
            if rule_count < 2:
                rep.add("p1", f"F09 {layout} 发丝线数量为 {rule_count}，应为 2（{where}）")
            pm = re.search(r'class="pageno">(\d+)<', block)
            if pm and int(pm.group(1)) != idx:
                rep.add("p1", f"F09 页码 {pm.group(1)} 与页序 {idx:02d} 不一致（{where}）")

        if layout == "M09":
            cards = len(re.findall(r'class="[^"]*\bcard\b', block))
            if cards > 4:
                rep.add("p1", f"F11 文献卡片 {cards} 张，单页上限 4 张（{where}）")

    return len(slides)


def check_pages_layout_specific(slides: list[str], rep: Report) -> None:
    for idx, block in enumerate(slides, start=1):
        layout = re.search(r'data-layout="([^"]*)"', block)
        layout = layout.group(1) if layout else ""
        where = f"第 {idx} 页"
        if layout == "M06":
            rows = len(re.findall(r'class="[^"]*\bbar-row\b', block))
            if rows > 10:
                rep.add("p2", f"M06 条形 {rows} 条，超过 10 条易溢出（{where}）")
        if layout == "M08":
            rows = len(re.findall(r'class="[^"]*\btopic-row\b', block))
            if rows > 8:
                rep.add("p2", f"M08 分桶 {rows} 条，超过 8 条易溢出（{where}）")
        if layout == "M07":
            if not has_class(block, "chart"):
                rep.add("p0", f"M07 缺少内联 SVG 趋势图（{where}）")
        for svg in re.findall(r"<svg\b[^>]*>", block):
            if 'role="img"' not in svg:
                rep.add("p1", f"无障碍：内联 SVG 缺少 role=\"img\"（{where}）")
            if 'aria-label' not in svg and "<title" not in block:
                rep.add("p1", f"无障碍：内联 SVG 缺少 aria-label（{where}）")


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a pubmed-retrieve HTML deck.")
    ap.add_argument("html", help="Path to the generated deck HTML")
    ap.add_argument("--strict", action="store_true", help="Treat P1 as failure too")
    args = ap.parse_args()

    with open(args.html, "r", encoding="utf-8") as fh:
        doc = fh.read()

    rep = Report()
    slides = SLIDE_RE.findall(doc)

    # --- CSS: style blocks + inline style attributes -----------------------
    for block in STYLE_BLOCK_RE.findall(doc):
        check_declarations(block, "<style> 块", rep)
        check_colors(block, "<style> 块", rep)
    for attr in STYLE_ATTR_RE.findall(doc):
        check_declarations(attr, "内联 style", rep)
        check_colors(attr, "内联 style", rep)
    for attr in PRESENTATION_ATTR_RE.findall(doc):
        if attr.strip().lower() in ("none", "currentcolor", "transparent", ""):
            continue
        check_colors(attr, "SVG 描边/填充", rep)

    # --- F08 external resources -------------------------------------------
    for pat, label in (
        (r"<img\b", "<img>"),
        (r"<link\b", "<link>"),
        (r"<script[^>]+\bsrc=", "<script src>"),
        (r"@import", "@import"),
        (r"\biframe\b", "<iframe>"),
    ):
        if re.search(pat, doc, re.IGNORECASE):
            rep.add("p0", f"F08 引入外部资源：{label}")
    for m in re.finditer(r'\b(?:src|href)="([^"]*)"', doc):
        url = m.group(1)
        if url.startswith(("http://", "https://", "//")):
            rep.add("p0", f"F08 引用外部 URL：{url}")

    # --- F12 alert budget --------------------------------------------------
    alert_uses = doc.count(ALERT_HEX) + doc.count("var(--alert)")
    if alert_uses > 2:
        rep.add("p1", f"F12 警示色出现 {alert_uses} 处，全篇上限 2 处")

    # --- structure ---------------------------------------------------------
    check_structure(doc, rep)
    check_pages_layout_specific(slides, rep)

    # --- report ------------------------------------------------------------
    print(f"[validate] {args.html}")
    print(f"[validate] pages: {len(slides)}")
    for level, label in (("p0", "P0 阻断"), ("p1", "P1 需确认"), ("p2", "P2 提示")):
        items = getattr(rep, level)
        if items:
            print(f"\n{label}（{len(items)}）")
            for it in items:
                print(f"  - {it}")
    if not (rep.p0 or rep.p1 or rep.p2):
        print("[validate] 全部通过：无 P0 / P1 / P2 问题")

    failed = bool(rep.p0) or (args.strict and bool(rep.p1))
    print(f"\n[validate] P0={len(rep.p0)} P1={len(rep.p1)} P2={len(rep.p2)} -> "
          f"{'FAIL' if failed else 'PASS'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

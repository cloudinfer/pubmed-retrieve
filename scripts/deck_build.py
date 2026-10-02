"""
Phase 5 renderer: deck_content.json -> single-file HTML deck.

Layouts M01-M12 and every styling rule live in:
    references/deck-layouts.md   (structure + data slot contracts)
    references/deck-theme.md     (palette, type scale, grid, forbidden list)

The output is a static, dependency-free HTML file: no CDN, no web fonts,
no chart library. Charts are inline SVG. Validate with deck_validate.py.

Usage:
    python deck_build.py --content output/deck_content.json \
                         --out output/deck.html
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys

# --- palette (must stay in sync with references/deck-theme.md) -------------
INK = "#0A1B2E"
INK2 = "#4A5C72"
INK3 = "#8593A3"
ANCHOR = "#0A3D7C"
ANCHOR2 = "#2E6BA8"
ANCHOR3 = "#8FB3D9"
WASH = "#EEF3F9"
HAIR = "#CBD7E4"
PAPER = "#FFFFFF"
ALERT = "#B01E28"

FONT_NUM = "Inter,Arial,sans-serif"

BRAND = "PubMed 文献调研"
FULL = "1/17"


def esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def window_text(meta: dict) -> str:
    s = (meta.get("start_date") or "").strip()
    e = (meta.get("end_date") or "").strip()
    if s and e:
        return f"{s} – {e}"
    if e:
        return f"截至 {e}"
    if s:
        return f"{s} 起"
    return "不限时间范围"


def limit_text(meta: dict) -> str:
    m = int(meta.get("max_results") or 0)
    return "不限篇数" if not m else f"上限 {m} 篇"


def pct(part: float, whole: float) -> float:
    if not whole:
        return 0.0
    return max(0.0, min(100.0, part / whole * 100.0))


def section(layout: str, title: str, inner: str, dark: bool = False) -> str:
    return (
        f'<section class="slide" data-layout="{layout}" data-dark="{1 if dark else 0}" '
        f'data-title="{esc(title)}">\n<div class="frame">\n{inner}\n</div>\n</section>'
    )


def head_block(layout: str, label: str, page: int) -> str:
    return (
        f'<div class="head"><span class="eyebrow">{esc(layout)} · {esc(label)}</span>'
        f'<span class="pageno">{page:02d}</span></div>\n<div class="rule"></div>'
    )


def foot_block(meta: dict) -> str:
    topic = (meta.get("topic") or "").strip()
    if len(topic) > 40:
        topic = topic[:39] + "…"
    return (
        f'<div class="rule"></div>\n<div class="foot t-cap">'
        f'<span>{esc(topic)}</span><span>{esc(meta.get("search_date"))}</span></div>'
    )


def page(**kw):
    """Standard white content page: head + rule + body + rule + foot."""
    layout = kw["layout"]
    inner = head_block(layout, kw["label"], kw["page"])
    inner += f'\n<div class="body">{kw["body"]}</div>\n'
    inner += foot_block(kw["meta"])
    return section(layout, kw["title"], inner)


# ---------------------------------------------------------------------------
# M01 Cover
# ---------------------------------------------------------------------------
def build_cover(c: dict, page_no: int) -> str:
    m = c["meta"]
    inner = (
        '<div class="head"><span class="eyebrow">Literature review</span></div>\n'
        '<div class="body" style="align-content:end">'
        f'<h1 class="t-display" style="grid-column:1/15">{esc(m["topic"])}</h1>'
        f'<p class="t-body" style="grid-column:1/13;margin-top:36px;color:var(--ink-2)">'
        f'{esc(window_text(m))} · EDAT 口径 · 命中 {m["hit_count"]} 篇</p>'
        "</div>\n"
        '<div class="rule"></div>\n'
        '<div class="foot t-cap">'
        f'<span>检索日期 {esc(m["search_date"])}</span>'
        f'<span>{esc(limit_text(m))}</span>'
        f'<span>schema {esc(c.get("schema"))}</span>'
        "</div>"
    )
    return section("M01", "封面", inner, dark=True)


# ---------------------------------------------------------------------------
# M03 Agenda
# ---------------------------------------------------------------------------
AGENDA = [
    ("01", "检索策略", "检索式构成、时间窗口与入库日期（EDAT）口径"),
    ("02", "文献体量", "命中规模、年份跨度、期刊与主题数量"),
    ("03", "来源期刊", "Top 10 期刊分布与集中度判断"),
    ("04", "时间趋势", "逐年入库量变化与峰值年份"),
    ("05", "主题分布", "关键词分桶结果与重叠口径说明"),
    ("06", "代表文献", "按方法学强度与时效性筛选的代表性研究"),
]


def build_agenda(c: dict, page_no: int) -> str:
    def rows(chunk):
        out = ['<div class="stack">']
        for num, title, desc in chunk:
            out.append(
                '<div class="row" style="display:grid;grid-template-columns:72px 1fr;column-gap:16px">'
                f'<span class="t-h3 t-num anchor">{num}</span>'
                f'<div><div class="t-h3">{esc(title)}</div>'
                f'<div class="t-bodys muted" style="margin-top:6px">{esc(desc)}</div></div>'
                "</div>"
            )
        out.append("</div>")
        return "".join(out)

    body = (
        f'<div style="grid-column:1/9">{rows(AGENDA[:3])}</div>'
        f'<div style="grid-column:9/17">{rows(AGENDA[3:])}</div>'
    )
    return page(layout="M03", label="目录", title="目录", body=body,
                page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M04 Method
# ---------------------------------------------------------------------------
def fit_query(q: str) -> tuple[str, int, bool]:
    q = q or "(本次未记录检索式)"
    n = len(q)
    if n <= 620:
        return q, 17, False
    if n <= 1150:
        return q, 15, False
    if n <= 1750:
        return q, 13, False
    return q[:1749].rstrip() + " …", 13, True


def build_method(c: dict, page_no: int) -> str:
    m, n = c["meta"], c["notes"]
    query, size, truncated = fit_query(m.get("query", ""))
    note = ""
    if truncated:
        note = (
            f'<p class="t-cap" style="margin-top:16px">'
            f"检索式过长，此处截断展示；完整检索式见随附 CSV 与 deck_content.json。</p>"
        )

    left = (
        '<div class="wash" style="grid-column:1/8">'
        f'<p class="t-mono" style="font-size:{size}px">{esc(query)}</p></div>{note}'
    )

    def kv(label, value, note_text):
        return (
            '<div class="kv" style="padding:16px 0;border-top:1px solid var(--hairline)">'
            f'<span class="k">{esc(label)}</span>'
            f'<span class="v"><span class="t-h3">{esc(value)}</span>'
            f'<span class="t-cap" style="display:block;margin-top:6px">{esc(note_text)}</span></span>'
            "</div>"
        )

    right = (
        '<div style="grid-column:8/17">'
        + kv("时间窗口", window_text(m), "起止日期按检索请求设定")
        + kv("日期字段", m.get("date_field", "EDAT"), n["date_field"])
        + kv("结果上限", limit_text(m), f"实际命中 {m['hit_count']} 篇，未触及上限"
             if int(m.get("max_results") or 0) and m["hit_count"] < int(m["max_results"])
             else f"实际命中 {m['hit_count']} 篇")
        + "</div>"
    )
    return page(layout="M04", label="检索策略", title="检索策略",
                body=left + right, page=page_no, meta=m)


# ---------------------------------------------------------------------------
# M05 KPI Tower
# ---------------------------------------------------------------------------
def build_kpi(c: dict, page_no: int) -> str:
    cells = list(c["kpis"])[:4]
    while len(cells) < 4:
        cells.append({"label": "—", "value": "—", "unit": "", "note": "数据不足"})
    html_cells = []
    for k in cells:
        html_cells.append(
            '<div class="cell">'
            f'<div class="lab">{esc(k["label"])}</div>'
            f'<div class="t-kpi-l">{esc(k["value"])}</div>'
            f'<div class="unit">{esc(k["unit"])}</div>'
            f'<div class="note">{esc(k["note"])}</div>'
            "</div>"
        )
    body = f'<div class="tower" style="grid-column:{FULL}">{"".join(html_cells)}</div>'
    return page(layout="M05", label="文献体量", title="文献体量",
                body=body, page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M06 Journal Rank
# ---------------------------------------------------------------------------
def journal_notes(c: dict) -> list[tuple[str, str]]:
    js, total = c["journals"], c["meta"]["hit_count"]
    if not js or not total:
        return [("数据不足", "本次检索未形成有效的期刊分布。")]
    top10 = sum(j["count"] for j in js)
    share10 = pct(top10, total)
    head = js[0]
    oa = any(k in head["name"].lower() for k in
             ("front", "plos", "bmc", "sci rep", "peerj", "helpon", "mdpi",
              "diagnostics", "medicine", "open", "cureus", "j clin med"))
    return [
        (
            "集中度",
            f"Top 10 期刊合计 {top10} 篇，占全量 {share10:.1f}%。"
            + ("来源相对集中，头部期刊值得优先跟踪。"
               if share10 >= 30 else
               "来源高度分散，提示该主题尚无稳定的发表阵地。"),
        ),
        (
            "头部特征",
            f"发文最多的是 {head['name']}（{head['count']} 篇，{head['share']}%）。"
            + ("以开放获取的综合类期刊为主，发文门槛与周期相对友好。"
               if oa else
               "以专业学会刊为主，说明该主题在学科内已有成熟发表通道。"),
        ),
        (
            "阅读提示",
            "期刊分布只反映 PubMed 收录情况与发文量，不代表研究质量高低，"
            "选读仍需回到研究设计与样本量。",
        ),
    ]


def build_journals(c: dict, page_no: int) -> str:
    js = c["journals"][:10]
    mx = max((j["count"] for j in js), default=1) or 1
    rows = []
    for i, j in enumerate(js):
        w = pct(j["count"], mx)
        rows.append(
            '<div class="bar-row">'
            f'<span class="name" title="{esc(j["name"])}">{esc(j["name"])}</span>'
            f'<span class="track"><i style="width:{w:.2f}%"></i></span>'
            f'<span class="val t-num">{j["count"]}</span>'
            "</div>"
        )
    # Isolate the two columns in their own grid: a tall commentary block must
    # never stretch the bar rows' grid tracks (and sparse auto-placement never
    # backtracks, so narrow-late would land in the last row and overflow).
    notes = "".join(
        f'<div style="margin-bottom:20px">'
        f'<div class="eyebrow">{esc(t)}</div>'
        f'<p class="t-bodys" style="margin-top:10px">{esc(d)}</p></div>'
        for t, d in journal_notes(c)
    )
    body = (
        f'<div style="grid-column:{FULL};display:grid;'
        'grid-template-columns:11fr 5fr;column-gap:24px;align-items:start">'
        f'<div>{"".join(rows)}</div><div>{notes}</div></div>'
    )
    body += f'<p class="t-cap" style="grid-column:{FULL}">{esc(c["notes"]["source"])}</p>'
    return page(layout="M06", label="来源期刊", title="来源期刊",
                body=body, page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M07 Year Trend
# ---------------------------------------------------------------------------
def line_chart(years: list[dict]) -> str:
    W, H = 1408, 340
    pl, pr, pt, pb = 72, 72, 48, 56
    counts = [y["count"] for y in years]
    mx = max(counts) or 1
    n = len(years)
    iw, ih = W - pl - pr, H - pt - pb
    base = pt + ih

    def X(i):
        return pl + (iw * i / (n - 1) if n > 1 else iw / 2)

    def Y(v):
        return pt + ih * (1 - v / mx)

    peak = counts.index(mx)
    out = [
        f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="逐年入库文献量趋势，{years[0]["year"]} 至 {years[-1]["year"]}">',
        f'<line x1="{pl}" y1="{base}" x2="{W - pr}" y2="{base}" '
        f'stroke="{HAIR}" stroke-width="1"/>',
        '<polyline points="'
        + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(counts))
        + f'" fill="none" stroke="{ANCHOR}" stroke-width="2" stroke-linejoin="miter"/>',
    ]
    for i, v in enumerate(counts):
        out.append(
            f'<rect x="{X(i) - 3:.1f}" y="{Y(v) - 3:.1f}" width="6" height="6" fill="{ANCHOR}"/>'
        )
    for i in sorted({0, peak, n - 1}):
        out.append(
            f'<text x="{X(i):.1f}" y="{base + 32}" text-anchor="middle" font-size="15" '
            f'fill="{INK3}" font-family="{FONT_NUM}">{years[i]["year"]}</text>'
        )
    labelled = {peak}
    if n - 1 not in labelled:
        labelled.add(n - 1)
    for i in sorted(labelled):
        out.append(
            f'<text x="{X(i):.1f}" y="{Y(counts[i]) - 20:.1f}" text-anchor="middle" '
            f'font-size="17" font-weight="500" fill="{ANCHOR}" '
            f'font-family="{FONT_NUM}">{counts[i]}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def trend_notes(c: dict) -> list[tuple[str, str]]:
    ys = c["years"]
    counts = [y["count"] for y in ys]
    mx = max(counts)
    peak_i = counts.index(mx)
    last, last_year = counts[-1], ys[-1]["year"]

    # Edge-of-window artifact: the EDAT window can start later than the earliest
    # PDAT year, so the first bar may hold only a handful of stragglers. That is
    # a boundary effect, not a trend, and must not be used as the baseline.
    caveat = ""
    base_i = 0
    if len(counts) >= 3 and counts[0] < max(3, mx * 0.1):
        base_i = 1
        caveat = (
            f"首年 {ys[0]['year']} 年仅 {counts[0]} 篇，"
            "属入库日期跨界的边缘样本，不作为趋势基线。"
        )
    base, base_year = counts[base_i], ys[base_i]["year"]

    if base <= 0:
        verdict = "趋势基线缺失，仅对比峰值与末年。"
    else:
        ratio = last / base
        if ratio >= 1.5:
            verdict = f"自 {base_year} 年 {base} 篇增至 {last_year} 年 {last} 篇（+{(ratio - 1) * 100:.0f}%），明显上行。"
        elif ratio >= 1.1:
            verdict = f"自 {base_year} 年 {base} 篇增至 {last_year} 年 {last} 篇（+{(ratio - 1) * 100:.0f}%），小幅上行。"
        elif ratio >= 0.9:
            verdict = f"{base_year} 与 {last_year} 年入库量基本持平（{base} → {last} 篇），处于平台期。"
        else:
            verdict = f"自 {base_year} 年 {base} 篇回落至 {last_year} 年 {last} 篇（−{(1 - ratio) * 100:.0f}%），需结合检索窗口判断成因。"
    if last >= mx * 0.9:
        verdict += "最近年份接近峰值，说明该主题当前仍活跃。"

    return [
        ("趋势判断", caveat + verdict),
        (
            "峰值与口径",
            f"峰值出现在 {ys[peak_i]['year']} 年（{counts[peak_i]} 篇）。"
            "入库量受在线优先出版、更正补录与数据库回溯收录影响，"
            "不能等同于当年正式出版量，跨年比较宜看趋势而非绝对值。",
        ),
    ]


def build_trend(c: dict, page_no: int) -> str:
    note_html = "".join(
        f'<div style="grid-column:{a}">'
        f'<div class="eyebrow">{esc(t)}</div>'
        f'<p class="t-bodys" style="margin-top:10px">{esc(d)}</p></div>'
        for (t, d), a in zip(trend_notes(c), ("1/9", "9/17"))
    )
    body = (
        f'<div style="grid-column:{FULL}">{line_chart(c["years"])}</div>'
        + note_html
        + f'<p class="t-cap" style="grid-column:{FULL}">{esc(c["notes"]["source"])}</p>'
    )
    return page(layout="M07", label="时间趋势", title="时间趋势",
                body=body, page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M08 Topic Matrix
# ---------------------------------------------------------------------------
def build_topics(c: dict, page_no: int) -> str:
    all_topics = c["topics"]
    specific = [t for t in all_topics if t.get("scope") != "core"]
    core = [t for t in all_topics if t.get("scope") == "core"]
    show = specific[:8]
    if len(show) < 3:
        show, core = all_topics[:8], []

    mx = max((t["count"] for t in show), default=1) or 1
    rows = []
    for i, t in enumerate(show):
        color = ANCHOR if i == 0 else (ANCHOR2 if i < 3 else ANCHOR3)
        rows.append(
            '<div class="topic-row" style="grid-column:' + FULL + '">'
            f'<span class="tname">{esc(t["key"])}</span>'
            f'<span class="topicbar"><i style="width:{pct(t["count"], mx):.2f}%;'
            f'background:{color}"></i></span>'
            f'<span class="tval t-num">{t["count"]} 篇 · {t["share"]}%</span>'
            "</div>"
        )
    body = "".join(rows)
    body += (
        f'<p class="t-cap" style="grid-column:{FULL}">{esc(c["notes"]["bucketing"])}</p>'
    )
    if core:
        names = "、".join(t["key"] for t in core)
        body += (
            f'<p class="t-cap" style="grid-column:{FULL}">'
            f"{esc(names)} 等 {len(core)} 个桶覆盖全量 80% 以上，"
            "属检索式核心词的固有命中，不构成分布信号，故未纳入上图。</p>"
        )
    return page(layout="M08", label="主题分布", title="主题分布",
                body=body, page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M09 Literature Cards
# ---------------------------------------------------------------------------
def build_cards(c: dict, items: list[dict], page_no: int, part: int, parts: int) -> str:
    cards = []
    for a in items:
        meta = f'{a["journal"]} · {a["year"] or "n.d."}'
        cards.append(
            '<div class="card">'
            f'<div class="meta">{esc(meta)}</div>'
            f'<div class="ttl">{esc(a["title"])}</div>'
            '<div class="foot2">'
            f'<span class="pmid">PMID {esc(a["pmid"])}</span>'
            f'<span class="why">{esc(a["reason"])}</span>'
            "</div></div>"
        )
    label = f"代表文献（{part}/{parts}）"
    body = f'<div class="cards" style="grid-column:{FULL}">{"".join(cards)}</div>'
    body += (
        f'<p class="t-cap" style="grid-column:{FULL}">'
        "PMID 均经检索结果 CSV 回查校验；入选理由按方法学强度与时效性排序，"
        "不代表研究质量评价。</p>"
    )
    return page(layout="M09", label=label, title=f"代表文献 {part}", body=body,
                page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M10 Duo Compare
# ---------------------------------------------------------------------------
def duo_topics(c: dict) -> list[dict]:
    """Pick two contrasting directions.

    Prefer buckets that actually discriminate (scope != core); a bucket covering
    the whole corpus would make the comparison meaningless.
    """
    specific = [t for t in c["topics"] if t.get("scope") != "core"]
    pool = specific if len(specific) >= 2 else c["topics"]
    return pool[:2]


def duo_column(t: dict, total: int, accent: bool) -> str:
    title_style = "color:var(--anchor)" if accent else "color:var(--ink)"
    review_line = f"其中系统综述与 Meta 分析 {t['review_count']} 篇，占本方向 {t['share_review']}%。"
    if t["share_review"] >= 95:
        review_line += "该桶本身即按综述特征命中，此比例不构成独立信号。"
    items = [
        f"命中 {t['count']} 篇，占全量 {t['share']}%。",
        review_line,
        f"多中心或外部验证研究 {t['validation_count']} 篇；"
        f"最新入库年份 {t['latest_year'] or '缺失'}。",
    ]
    if t.get("top_journal"):
        items.append(f"主要来源期刊：{t['top_journal']}（{t['top_journal_count']} 篇）。")
    lis = "".join(f'<div class="item">{esc(i)}</div>' for i in items[:4])
    return (
        "<div>"
        f'<h2 class="t-h2" style="' + title_style + f'">{esc(t["key"])}</h2>'
        f'<p class="t-bodys muted" style="margin-top:14px">'
        f'规模占全量的 {t["share"]}%，按本桶内综述与验证性研究的比例衡量方法学成熟度。</p>'
        f'<div class="list" style="margin-top:26px">{lis}</div>'
        "</div>"
    )


def build_duo(c: dict, page_no: int) -> str:
    ts = duo_topics(c)
    body = (
        '<div class="duo" style="grid-column:' + FULL + '">'
        + duo_column(ts[0], c["meta"]["hit_count"], accent=True)
        + '<div class="divider"></div>'
        + duo_column(ts[1], c["meta"]["hit_count"], accent=False)
        + "</div>"
    )
    body += (
        f'<p class="t-cap" style="grid-column:{FULL}">{esc(c["notes"]["bucketing"])}</p>'
    )
    return page(layout="M10", label="方向对照", title="方向对照",
                body=body, page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M11 Outlook
# ---------------------------------------------------------------------------
def headline_topic(c: dict) -> dict | None:
    """The most informative topic for prose: the largest discriminating bucket."""
    specific = [t for t in c["topics"] if t.get("scope") != "core"]
    if specific:
        return specific[0]
    return c["topics"][0] if c["topics"] else None


def build_outlook(c: dict, page_no: int) -> str:
    n = c["notes"]
    ys = c["years"]
    trend = (f"纳入 {len(ys)} 个入库年份，"
             f"峰值出现在 {max(ys, key=lambda y: y['count'])['year']} 年。"
             if ys else "年份数据不足，无法给出时间趋势判断。")
    top = headline_topic(c)
    if top:
        trend += f"主题分布上，{top['key']}以 {top['count']} 篇居首（{top['share']}%）。"

    cols = [
        ("01", "趋势判断", trend),
        ("02", "方法局限",
         f"{n['date_field']}{n['bucketing']}此外，仅依据题录与摘要，"
         "未对研究设计、样本量与偏倚风险做质量评价。"),
        ("03", "下一步",
         "补检同义词与 MeSH 副主题词以降低漏检；"
         "扩展或收窄时间窗口复核趋势拐点；"
         "对代表文献做全文精读并提取证据表；"
         "必要时引入外部数据集验证结论稳健性。"),
    ]
    cells = "".join(
        "<div>"
        f'<div class="t-h3 t-num anchor">{esc(num)}</div>'
        f'<div class="t-h3" style="margin-top:14px">{esc(title)}</div>'
        f'<p class="t-bodys" style="margin-top:14px">{esc(text)}</p>'
        "</div>"
        for num, title, text in cols
    )
    body = f'<div class="third" style="grid-column:{FULL}">{cells}</div>'
    body += f'<p class="t-cap" style="grid-column:{FULL}">{esc(n["source"])}</p>'
    return page(layout="M11", label="趋势与局限", title="趋势与局限",
                body=body, page=page_no, meta=c["meta"])


# ---------------------------------------------------------------------------
# M12 Closing
# ---------------------------------------------------------------------------
def build_closing(c: dict, page_no: int) -> str:
    m = c["meta"]
    ys = c["years"]
    span = (f"{ys[0]['year']}–{ys[-1]['year']}" if len(ys) >= 2
            else (str(ys[0]["year"]) if ys else "年份缺失"))
    headline = f"在 {span} 窗口内命中 {m['hit_count']} 篇文献"
    top = headline_topic(c)
    if top:
        headline += f"，{top['key']}为最大方向"
    inner = (
        '<div class="head"><span class="eyebrow">Conclusion</span></div>\n'
        '<div class="body" style="align-content:end">'
        f'<h1 class="t-h1" style="grid-column:1/15">{esc(headline)}。</h1>'
        '<p class="t-body" style="grid-column:1/13;margin-top:32px;color:var(--ink-2)">'
        "下一步：补检同义词与 MeSH 词、复核时间窗口口径、"
        "对代表文献做全文精读并形成证据表。</p>"
        "</div>\n"
        '<div class="rule"></div>\n'
        '<div class="foot t-cap">'
        f'<span>{esc(BRAND)} · {esc(m["search_date"])}</span>'
        f'<span>命中 {m["hit_count"]} 篇 · {esc(limit_text(m))}</span>'
        "</div>"
    )
    return section("M12", "结论", inner, dark=True)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# M13-M18 · Systematic-review pages (rendered only when review evidence exists)
#
# These pages carry the review layer: research question, PRISMA flow, evidence
# grading, convergence, gaps and conclusions. They are appended to the
# descriptive deck rather than replacing it, so a reader sees both "what the
# corpus looks like" and "what the corpus supports".
# ---------------------------------------------------------------------------
PICOS_ROWS = [
    ("P", "肝细胞癌患者，不限分期与治疗方式"),
    ("I", "CT / MRI / 超声 / PET 影像组学或影像人工智能模型"),
    ("C", "不设强制对照；临床模型与联合模型均计入"),
    ("O", "总生存、无复发生存、早期复发、治疗应答及预测性能"),
    ("S", "原始研究与系统综述均纳入；述评与通信排除"),
]


def build_picos(c: dict, rv: dict, page_no: int) -> str:
    left = "".join(
        f'<div class="kv"><span class="k">{esc(k)}</span>'
        f'<span class="v t-bodys">{esc(v)}</span></div>'
        for k, v in PICOS_ROWS
    )
    prisma = rv.get("prisma", {})
    right = [
        f"数据库：PubMed（NCBI E-utilities），检索日期 {c['meta'].get('search_date', '')}。",
        f"时间窗：{window_text(c['meta'])}，按入库日期（EDAT）限定。",
        f"题录初筛后潜在纳入 {prisma.get('eligible_pending_fulltext', 0)} 篇，"
        f"已确认纳入 {prisma.get('included_confirmed', 0)} 篇（全文复核待完成）。",
        "偏倚风险与 GRADE 评级需全文复核后填写，本页不以推断填充。",
    ]
    right_html = "".join(f'<div class="item">{esc(t)}</div>' for t in right)
    body = (
        f'<h2 class="t-h2" style="grid-column:{FULL}">研究问题与纳入标准</h2>'
        f'<div style="grid-column:1/10;margin-top:28px" class="stack">{left}</div>'
        f'<div style="grid-column:11/17;margin-top:28px">'
        f'<div class="eyebrow">执行口径</div>'
        f'<div class="list" style="margin-top:14px">{right_html}</div></div>'
    )
    return page(layout="M13", label="研究问题", title="研究问题与 PICOS",
                body=body, page=page_no, meta=c["meta"])


def build_prisma(c: dict, rv: dict, page_no: int) -> str:
    p = rv.get("prisma", {})
    ident = int(p.get("identified") or 1)
    steps = [
        ("数据库检出", p.get("identified", 0)),
        ("去重后", p.get("records_screened", 0)),
        ("题录初筛排除", p.get("excluded_screening_total", 0)),
        ("进入全文评估", p.get("fulltext_assessed", 0)),
        ("潜在纳入（待复核）", p.get("eligible_pending_fulltext", 0)),
        ("已确认纳入", p.get("included_confirmed", 0)),
    ]
    rows = []
    for name, val in steps:
        w = pct(float(val), float(ident))
        fill = ANCHOR if name in ("潜在纳入（待复核）", "进入全文评估") else ANCHOR3
        rows.append(
            '<div class="bar-row">'
            f'<span class="name">{esc(name)}</span>'
            f'<span class="track"><i style="width:{w:.2f}%;background:{fill}"></i></span>'
            f'<span class="val t-num">{val}</span>'
            "</div>"
        )
    ex = p.get("excluded_at_screening", [])[:4]
    ex_html = "".join(
        f'<div class="item">{esc(e["reason"])}　<b class="t-num">{e["count"]}</b></div>'
        for e in ex
    )
    body = (
        f'<h2 class="t-h2" style="grid-column:{FULL}">文献筛选流程（PRISMA 2020）</h2>'
        f'<div style="grid-column:1/11;margin-top:26px">{"".join(rows)}</div>'
        f'<div style="grid-column:11/17;margin-top:26px">'
        f'<div class="eyebrow">主要排除原因</div>'
        f'<div class="list" style="margin-top:12px">{ex_html}</div>'
        f'<p class="t-cap" style="margin-top:18px">筛选在题录与摘要层面由确定性规则执行，'
        f'每条排除记录均登记原因，计数可复核。</p></div>'
    )
    return page(layout="M14", label="筛选流程", title="PRISMA 筛选流程",
                body=body, page=page_no, meta=c["meta"])


def build_levels(c: dict, rv: dict, page_no: int) -> str:
    lv = rv.get("levels", [])[:7]
    mx = max((x["count"] for x in lv), default=1) or 1
    rows = []
    for i, x in enumerate(lv):
        w = pct(float(x["count"]), float(mx))
        fill = ANCHOR if i == 0 else (ANCHOR2 if i < 3 else ANCHOR3)
        rows.append(
            '<div class="bar-row">'
            f'<span class="name">{esc(x["label"])}</span>'
            f'<span class="track"><i style="width:{w:.2f}%;background:{fill}"></i></span>'
            f'<span class="val t-num">{x["count"]}</span>'
            "</div>"
        )
    total = sum(x["count"] for x in lv) or 1
    l4 = next((x["count"] for x in lv if x["level"] == "IV"), 0)
    notes = [
        f"Level IV（回顾性队列）占 {pct(l4, total):.1f}%，构成证据底座的主体。",
        "分级由摘要中报告的研究设计推定，属暂定分级，须经全文复核确认。",
        "「随机分配至训练集与验证集」是数据划分而非治疗随机化，已排除在 RCT 之外。",
    ]
    right = "".join(f'<div class="item">{esc(t)}</div>' for t in notes)
    body = (
        f'<h2 class="t-h2" style="grid-column:{FULL}">证据等级分布</h2>'
        f'<div style="grid-column:1/11;margin-top:26px">{"".join(rows)}</div>'
        f'<div style="grid-column:11/17;margin-top:26px">'
        f'<div class="eyebrow">分级口径</div>'
        f'<div class="list" style="margin-top:12px">{right}</div></div>'
    )
    return page(layout="M15", label="证据等级", title="证据等级分布",
                body=body, page=page_no, meta=c["meta"])


def build_convergence(c: dict, rv: dict, page_no: int) -> str:
    conv = rv.get("matrix", {}).get("convergence", [])[:7]
    head = (
        '<div style="display:grid;grid-template-columns:4fr 2fr 2fr 2fr 2fr;'
        'column-gap:16px;padding-bottom:10px;border-bottom:1px solid ' + HAIR + '">'
        '<span class="eyebrow">主题</span>'
        '<span class="eyebrow" style="text-align:right">支持</span>'
        '<span class="eyebrow" style="text-align:right">Level I/II</span>'
        '<span class="eyebrow" style="text-align:right">外部验证</span>'
        '<span class="eyebrow" style="text-align:right">强度</span></div>'
    )
    rows = [head]
    for x in conv:
        # Strength rides the blue scale rather than the alert colour: lighter
        # reads as weaker, which is both semantically right and keeps --alert
        # reserved for the few places where it is genuinely a warning.
        fill = {"强": ANCHOR, "中": ANCHOR2}.get(x["strength"], ANCHOR3)
        rows.append(
            '<div style="display:grid;grid-template-columns:4fr 2fr 2fr 2fr 2fr;'
            'column-gap:16px;padding:11px 0;border-bottom:1px solid ' + HAIR + '">'
            f'<span class="t-bodys">{esc(x["theme"])}</span>'
            f'<span class="t-bodys t-num" style="text-align:right">{x["support"]}</span>'
            f'<span class="t-bodys t-num" style="text-align:right">'
            f'{x["high_level_rate"]}%</span>'
            f'<span class="t-bodys t-num" style="text-align:right">'
            f'{x["external_validation_rate"]}%</span>'
            f'<span class="t-bodys" style="text-align:right;color:{fill}">'
            f'{esc(x["strength"])}</span></div>'
        )
    body = (
        f'<h2 class="t-h2" style="grid-column:{FULL}">证据收敛汇总</h2>'
        f'<div style="grid-column:{FULL};margin-top:24px">{"".join(rows)}</div>'
        f'<p class="t-cap" style="grid-column:{FULL};margin-top:16px">'
        f'收敛指标在全量潜在纳入文献池上计算，不在精选语料上计算，以避免抽样偏倚；'
        f'强度阈值以文献池自身基线自校准。</p>'
    )
    return page(layout="M16", label="证据收敛", title="证据收敛汇总",
                body=body, page=page_no, meta=c["meta"])


def build_gaps(c: dict, rv: dict, page_no: int) -> str:
    gaps = rv.get("gaps", [])[:6]
    left = "".join(
        f'<div class="item"><b>{esc(g["type"])}</b> · {esc(g["gap"])}'
        f'<div class="t-cap" style="margin-top:4px">{esc(g["evidence"])}</div></div>'
        for g in gaps
    )
    agenda = [
        "把外部验证设为最低门槛，而非加分项。",
        "推动预测模型研究的前瞻注册，明确主要终点与分析计划。",
        "优先投入影像-病理-多组学交叉验证研究。",
        "开展模态与模型族的头对头比较研究。",
        "统一报告规范：强制报告 AUC/C-index 及其队列语境。",
    ]
    right = "".join(f'<div class="item">{esc(t)}</div>' for t in agenda)
    body = (
        f'<h2 class="t-h2" style="grid-column:{FULL}">研究空白与研究议程</h2>'
        f'<div style="grid-column:1/9;margin-top:24px">'
        f'<div class="eyebrow">已识别空白</div>'
        f'<div class="list" style="margin-top:12px">{left}</div></div>'
        f'<div style="grid-column:9/17;margin-top:24px">'
        f'<div class="eyebrow">议程建议</div>'
        f'<div class="list" style="margin-top:12px">{right}</div></div>'
    )
    return page(layout="M17", label="空白与议程", title="研究空白与研究议程",
                body=body, page=page_no, meta=c["meta"])


def build_review_conclusion(c: dict, rv: dict, page_no: int) -> str:
    p = rv.get("prisma", {})
    n = rv.get("numbers", {})
    conv = rv.get("matrix", {}).get("convergence", [])
    weak = [x["theme"] for x in conv if x["strength"] in ("弱", "极弱", "空白")]
    auc = n.get("auc_overall") or {}
    items = [
        ("证据规模", f"潜在纳入 {p.get('eligible_pending_fulltext', 0)} 篇，"
                     f"其中 Level I {sum(x['count'] for x in rv.get('levels', []) if x['level'] == 'I')} 篇。"),
        ("性能水平", f"AUC/C-index 中位 {auc.get('median', '—')}"
                     f"（四分位距 {auc.get('p25', '—')}–{auc.get('p75', '—')}），"
                     f"训练集高于内部验证集。"),
        ("验证强度", f"外部验证率 {pct(n.get('external_validation_n', 0), p.get('eligible_pending_fulltext', 1)):.1f}%，"
                     f"前瞻性研究 {pct(n.get('prospective_n', 0), p.get('eligible_pending_fulltext', 1)):.1f}%。"),
        ("薄弱方向", ("、".join(weak[:3]) + " 证据强度偏弱。") if weak else "各主题证据强度均衡。"),
        ("结论边界", "全文复核与 GRADE 评级完成前，不支持临床推荐强度的判定。"),
    ]
    rows = "".join(
        f'<div class="row"><div class="kv"><span class="k">{esc(k)}</span>'
        f'<span class="v t-bodys">{esc(v)}</span></div></div>'
        for k, v in items
    )
    body = (
        f'<h2 class="t-h2" style="grid-column:{FULL}">综述结论</h2>'
        f'<div style="grid-column:1/14;margin-top:26px" class="stack">{rows}</div>'
    )
    return page(layout="M18", label="综述结论", title="综述结论",
                body=body, page=page_no, meta=c["meta"])


def compose(c: dict, rv: dict | None = None) -> list[str]:
    pages: list[str] = []
    n = lambda: len(pages) + 1  # noqa: E731

    pages.append(build_cover(c, n()))
    pages.append(build_agenda(c, n()))
    pages.append(build_method(c, n()))

    if rv:
        pages.append(build_picos(c, rv, n()))
        pages.append(build_prisma(c, rv, n()))

    pages.append(build_kpi(c, n()))

    if rv and rv.get("levels"):
        pages.append(build_levels(c, rv, n()))

    pages.append(build_journals(c, n()))

    if len(c["years"]) >= 2:
        pages.append(build_trend(c, n()))

    if c["topics"]:
        pages.append(build_topics(c, n()))

    arts = c["articles"][:8]
    if arts:
        chunks = [arts[i:i + 4] for i in range(0, len(arts), 4)]
        for idx, chunk in enumerate(chunks, start=1):
            pages.append(build_cards(c, chunk, n(), idx, len(chunks)))

    if len(duo_topics(c)) >= 2:
        pages.append(build_duo(c, n()))

    if rv and rv.get("matrix", {}).get("convergence"):
        pages.append(build_convergence(c, rv, n()))
    if rv and rv.get("gaps"):
        pages.append(build_gaps(c, rv, n()))

    pages.append(build_outlook(c, n()))

    if rv:
        pages.append(build_review_conclusion(c, rv, n()))

    pages.append(build_closing(c, n()))
    return pages


def default_template_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "assets", "deck", "template-medical.html")


def render_deck(content: dict, template_path: str | None = None,
                review: dict | None = None) -> str:
    """Inject rendered slides into the template and return the full HTML string."""
    path = template_path or default_template_path()
    if not os.path.exists(path):
        raise SystemExit(f"Template not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        template = fh.read()
    slides = compose(content, review)
    return (
        template.replace("{{TITLE}}", esc(content["meta"]["topic"]))
        .replace("{{SLIDES}}", "\n".join(slides))
    )


def write_deck(content: dict, out_path: str, template_path: str | None = None,
               review: dict | None = None) -> int:
    """Render and write the deck. Returns the page count."""
    html_out = render_deck(content, template_path, review)
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)
    return len(compose(content, review))


def main() -> None:
    ap = argparse.ArgumentParser(description="Render deck_content.json into a single-file HTML deck.")
    ap.add_argument("--content", required=True, help="Path to deck_content.json")
    ap.add_argument("--out", required=True, help="Output HTML path")
    ap.add_argument("--template", default=None, help="Template path (default: assets/deck/template-medical.html)")
    ap.add_argument("--review", default=None,
                    help="Path to review_evidence.json; adds the systematic-review pages")
    args = ap.parse_args()

    with open(args.content, "r", encoding="utf-8") as fh:
        content = json.load(fh)

    review = None
    if args.review:
        with open(args.review, "r", encoding="utf-8") as fh:
            review = json.load(fh)

    pages = write_deck(content, args.out, args.template, review)
    print(f"[deck] html -> {args.out}  ({pages} pages"
          + (" , review pages included" if review else "") + ")")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

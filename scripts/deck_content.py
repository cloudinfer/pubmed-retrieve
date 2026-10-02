"""
Deck content model builder for pubmed-retrieve (Phase 6).

Reads the retrieval CSV produced by pubmed_cli.py and emits:
  - deck_content.json : the single source of truth consumed by deck_build.py
                        and by the .pptx pipeline (tencent-pptx).
  - deck_outline.md   : a plain-markdown outline of the deck (page by page),
                        usable as source material by any PPT generator.

Contract is frozen in references/deck-layouts.md section 0. Keep field names
stable; bump SCHEMA if anything changes.

Usage:
    python deck_content.py \
        --csv output/pubmed_results.csv \
        --out-dir output \
        --topic "radiomics in hepatocellular carcinoma prognosis" \
        --query-file .workbuddy/tmp_query.txt \
        --start 2021/01/01 --end 2026/10/02 --max-results 2000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

import pandas as pd

SCHEMA = "pubmed-deck/1"

# ---------------------------------------------------------------------------
# Topic buckets.
#
# NOTE ON REGEX SAFETY: every short token needs \b boundaries. Real-world
# traps documented in SKILL.md: `spect` matches re*spect*ive / retro*spect*ive,
# `oral` matches tem*poral*, `ct` matches dete*ct*, `us` matches the pronoun
# "us". Never drop the \b on tokens of three characters or fewer.
# ---------------------------------------------------------------------------
DEFAULT_TOPICS = {
    "深度学习": r"\bdeep learning\b|convolutional|\bcnn\b|transformer|neural network|\bu-net\b|foundation model",
    "影像组学与机器学习": r"radiomic|machine learning|random forest|xgboost|nomogram|\bsvm\b|lasso|signature",
    "系统综述与Meta分析": r"systematic review|meta-analys|scoping review|umbrella review|evidence map",
    "临床试验与干预研究": r"randomi[sz]ed|\brct\b|clinical trial|phase (?:\bi{1,3}\b|\biv\b)|intervention",
    "影像与内镜模态": r"\bct\b|computed tomograph|cone-beam|\bcbct\b|\bmri\b|magnetic resonance|\bultrasound\b|\bpet\b|\bspect\b|dual-energy|endoscop",
    "分子与组学标志物": r"genomic|transcriptom|proteom|single-cell|\brna-seq\b|sequencing|mutation|biomarker|circulating",
    "预后与生存分析": r"prognos|survival|recurrence|hazard ratio|\bpfs\b|\bos\b|risk stratif",
    "治疗与免疫": r"immunotherap|chemotherap|targeted therap|radiotherapy|immune|tumor microenvironment|adjuvant",
    "多中心与外部验证": r"multicent|multi-cent|external validation|generalizab|prospective|real-world",
    "流行病学与人群研究": r"epidemiolog|public health|incidence|prevalence|population-based|cohort study",
}

REVIEW_PAT = r"systematic review|meta-analys|scoping review|umbrella review|guideline|consensus"
VALIDATION_PAT = r"multicent|multi-cent|external validation|prospective|real-world|generalizab"

# A bucket covering >= this share of the corpus is treated as "core": it is
# almost certainly echoing the query's own core terms and therefore says
# nothing about composition. See references/deck-layouts.md section 3.
CORE_BUCKET_SHARE = 80.0

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
TRUNC_TITLE = 190


def load_query(path: str | None, inline: str | None) -> str:
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip().replace("\n", " ")
    return (inline or "").strip()


def load_topics(path: str | None) -> dict[str, str]:
    if not path:
        return dict(DEFAULT_TOPICS)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data:
        raise SystemExit("--topics-file must be a non-empty JSON object of {name: regex}")
    return {str(k): str(v) for k, v in data.items()}


def pick_year(raw) -> int | None:
    m = YEAR_RE.search(str(raw or ""))
    return int(m.group(0)) if m else None


def clean(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def truncate(text: str, limit: int) -> str:
    text = clean(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df["Pmid"] = df["Pmid"].astype(str).str.strip()
    df = df[df["Pmid"].notna() & (df["Pmid"] != "") & (df["Pmid"].str.lower() != "nan")]

    records = []
    for row in df.to_dict("records"):
        records.append(
            {
                "pmid": row["Pmid"],
                "title": clean(row.get("Title")),
                "journal": clean(row.get("Journal")) or "未标注期刊",
                "year": pick_year(row.get("Date")),
                "doi": clean(row.get("Doi")),
                "abstract": clean(row.get("Abstract")),
            }
        )
    return records


def bucket_topics(records: list[dict], patterns: dict[str, str]) -> list[dict]:
    compiled = {k: re.compile(v, re.IGNORECASE) for k, v in patterns.items()}
    review_rx = re.compile(REVIEW_PAT, re.IGNORECASE)
    valid_rx = re.compile(VALIDATION_PAT, re.IGNORECASE)
    total = len(records) or 1

    # Single pass over records: tag topics and precompute per-record flags.
    stats: dict[str, dict] = {k: {"count": 0, "review": 0, "validation": 0,
                                  "latest": None, "journals": Counter()} for k in patterns}
    for rec in records:
        haystack = f"{rec['title']} {rec['abstract']}"
        rec["topics"] = [k for k, rx in compiled.items() if rx.search(haystack)]
        is_review = bool(review_rx.search(haystack))
        is_valid = bool(valid_rx.search(haystack))
        for key in rec["topics"]:
            st = stats[key]
            st["count"] += 1
            st["review"] += int(is_review)
            st["validation"] += int(is_valid)
            if rec["year"] and (st["latest"] is None or rec["year"] > st["latest"]):
                st["latest"] = rec["year"]
            st["journals"][rec["journal"]] += 1

    ordered = sorted(((k, v) for k, v in stats.items() if v["count"] > 0),
                     key=lambda kv: (-kv[1]["count"], kv[0]))

    result = []
    for name, st in ordered:
        count = st["count"]
        share = round(count / total * 100, 1)
        top_journal = st["journals"].most_common(1)
        result.append(
            {
                "key": name,
                "count": count,
                "share": share,
                # A bucket that covers nearly the whole corpus carries no
                # distributional signal: it just echoes the query's own core
                # terms (e.g. "radiomics" in a radiomics query). Mark it so the
                # renderer can keep it out of the "topic distribution" headline.
                "scope": "core" if share >= CORE_BUCKET_SHARE else "specific",
                "pattern": patterns[name],
                "review_count": st["review"],
                "share_review": round(st["review"] / count * 100, 1) if count else 0.0,
                "validation_count": st["validation"],
                "latest_year": st["latest"],
                "top_journal": top_journal[0][0] if top_journal else "",
                "top_journal_count": top_journal[0][1] if top_journal else 0,
            }
        )
    return result


def select_articles(records: list[dict], max_items: int = 8, per_topic: int = 2) -> list[dict]:
    scored = []
    year_rank = max((r["year"] or 0) for r in records) if records else 0
    for rec in records:
        hay = f"{rec['title']} {rec['abstract']}"
        score, reason = 0, "最新发表"
        # Ranking may look at title + abstract, but the LABEL must come from the
        # title only. Abstracts routinely mention "previous systematic reviews"
        # or "a meta-analysis was performed", which would mislabel a primary
        # study as a review.
        if re.search(REVIEW_PAT, hay, re.IGNORECASE):
            score += 4
            if re.search(REVIEW_PAT, rec["title"], re.IGNORECASE):
                reason = "系统综述 / Meta 分析"
        if re.search(VALIDATION_PAT, hay, re.IGNORECASE):
            score += 3
            if reason == "最新发表" and re.search(VALIDATION_PAT, rec["title"], re.IGNORECASE):
                reason = "多中心 / 外部验证"
        if rec["year"]:
            score += max(0, 3 - (year_rank - rec["year"]))
        scored.append((score, reason, rec))

    scored.sort(key=lambda t: (-t[0], -(t[2]["year"] or 0)))

    chosen, seen_topics, seen_pmid = [], Counter(), set()
    for score, reason, rec in scored:
        if len(chosen) >= max_items:
            break
        if rec["pmid"] in seen_pmid:
            continue
        primary = rec["topics"][0] if rec["topics"] else "其他"
        if seen_topics[primary] >= per_topic:
            continue
        seen_topics[primary] += 1
        seen_pmid.add(rec["pmid"])
        chosen.append(
            {
                "pmid": rec["pmid"],
                "title": truncate(rec["title"], TRUNC_TITLE),
                "journal": rec["journal"],
                "year": rec["year"],
                "topic": primary,
                "reason": reason,
            }
        )
    return chosen


def build_kpis(records: list[dict], n_journals: int, topics: list[dict], years: list[dict]) -> list[dict]:
    years_present = sorted({r["year"] for r in records if r["year"]})
    if len(years_present) >= 2:
        span, span_note = str(years_present[-1] - years_present[0] + 1), f"{years_present[0]}–{years_present[-1]}"
    elif years_present:
        span, span_note = "1", str(years_present[0])
    else:
        span, span_note = "—", "年份缺失"

    return [
        {
            "label": "命中文献",
            "value": f"{len(records)}",
            "unit": "篇",
            "note": "EDAT 口径",
        },
        {
            "label": "年份跨度",
            "value": span,
            "unit": "年",
            "note": span_note,
        },
        {
            "label": "来源期刊",
            "value": f"{n_journals}",
            "unit": "种",
            "note": "全量去重",
        },
        {
            "label": "主题领域",
            "value": f"{len(topics)}",
            "unit": "个",
            "note": "可多重归类",
        },
    ]


def build_content(args) -> dict:
    if not os.path.exists(args.csv):
        raise SystemExit(f"CSV not found: {args.csv}")

    df = pd.read_csv(args.csv)
    required = {"Pmid", "Title", "Journal"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"CSV missing required columns: {sorted(missing)}")

    records = build_records(df)
    if not records:
        raise SystemExit("CSV contains no usable records (empty Pmid column).")

    patterns = load_topics(args.topics_file)
    topics = bucket_topics(records, patterns)

    journal_counter = Counter(r["journal"] for r in records)
    total = len(records)
    journals = [
        {"name": name, "count": cnt, "share": round(cnt / total * 100, 1)}
        for name, cnt in journal_counter.most_common(10)
    ]

    year_counter = Counter(r["year"] for r in records if r["year"])
    years = [{"year": y, "count": c} for y, c in sorted(year_counter.items())]

    query = load_query(args.query_file, args.query)
    top_pub_year = max(year_counter) if year_counter else None

    notes = {
        "date_field": (
            "检索按 EDAT（文献进入 PubMed 的入库日期）筛选，"
            "与期刊正式出版月不完全一致；在线优先出版与补录文献会一并计入。"
        ),
        "bucketing": (
            "主题分桶由标题与摘要的关键词命中生成，同一文献可归属多个主题，"
            "各桶占比之和大于 100%，不构成互斥分类。"
        ),
        "source": f"数据来源：PubMed（NCBI E-utilities），检索日期 {args.search_date}。",
    }

    meta = {
        "topic": args.topic or "(未命名主题)",
        "query": query,
        "start_date": args.start or "",
        "end_date": args.end or "",
        "search_date": args.search_date,
        "date_field": "EDAT（PubMed 入库日期）",
        "max_results": int(args.max_results),
        "hit_count": total,
        "latest_pub_year": top_pub_year,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    articles = select_articles(records, max_items=args.max_articles)

    content = {
        "schema": SCHEMA,
        "meta": meta,
        "kpis": build_kpis(records, len(journal_counter), topics, years),
        "journals": journals,
        "years": years,
        "topics": topics,
        "articles": articles,
        "notes": notes,
    }

    # The review layer rides inside the content model rather than being passed
    # separately to each consumer. The outline written here is the only material
    # the PPT step receives, so a review layer that lives only in a CLI flag
    # silently drops out of the slides.
    review_path = getattr(args, "review", None)
    if review_path:
        if not os.path.exists(review_path):
            raise SystemExit(f"--review not found: {review_path}")
        with open(review_path, encoding="utf-8") as fh:
            content["review"] = review_digest(json.load(fh))
        meta["review_source"] = os.path.basename(review_path)
        meta["review_layers"] = sorted(
            m for m in ("prisma", "levels", "numbers", "gaps", "matrix")
            if content["review"].get(m)
        )
    else:
        meta["review_source"] = None
        meta["review_layers"] = []
    return content


# ---------------------------------------------------------------------------
# Review layer.
#
# The deck is the *last* stage of the pipeline, not the first. The systematic
# review is composed first, and the deck then renders its review layer from the
# review's own evidence base. That ordering is the reason this module accepts
# --review at all: the outline it writes is the hand-off material for the .pptx,
# so a review layer that is missing here never reaches the slides.
# ---------------------------------------------------------------------------
REVIEW_LIST_KEYS = ("prisma", "levels", "numbers", "gaps", "themes")
REVIEW_META_KEYS = ("topic", "search_date", "criteria_source",
                    "picos", "picos_source", "picos_available")


def review_digest(rv: dict) -> dict:
    """Compact copy of the review layer, embedded in ``deck_content.json``.

    Only the fields ``deck_build.py`` actually reads are kept, so the content
    model stays small enough to read while remaining the single source of truth
    for both the HTML deck and the outline handed to the PPT step.
    """
    out = {k: rv[k] for k in REVIEW_LIST_KEYS if k in rv}
    out["matrix"] = {"convergence": (rv.get("matrix") or {}).get("convergence", [])}
    rmeta = rv.get("meta") or {}
    out["meta"] = {k: rmeta[k] for k in REVIEW_META_KEYS if k in rmeta}
    return out


# ---------------------------------------------------------------------------
# Markdown outline — the hand-off format for the .pptx pipeline.
# ---------------------------------------------------------------------------
FALLBACK_SEQ = [
    ("M01", "封面"), ("M03", "目录"), ("M04", "检索策略"), ("M05", "文献体量"),
    ("M06", "来源期刊"), ("M07", "时间趋势"), ("M08", "主题分布"),
    ("M09", "代表文献 1"), ("M10", "方向对照"), ("M11", "趋势与局限"),
    ("M12", "结论"),
]


def page_sequence(c: dict) -> list[tuple[str, str]]:
    """``(layout, title)`` for every page the HTML deck renders, in order.

    Reading the sequence back off the renderer is what keeps the two artifacts
    from drifting. The outline is the only material the PPT step receives, so if
    the deck gains a review page the outline has to gain it too — without anyone
    having to remember that a second list exists.
    """
    try:
        import deck_build as db  # no reverse dependency: deck_build never imports us
    except ImportError:
        return list(FALLBACK_SEQ)
    html = "\n".join(db.compose(c, c.get("review") or None))
    seq = re.findall(r'data-layout="(M\d+)"[^>]*data-title="([^"]*)"', html)
    return seq or list(FALLBACK_SEQ)


def _article_chunks(c: dict) -> list[list[dict]]:
    arts = c["articles"][:8]
    return [arts[i:i + 4] for i in range(0, len(arts), 4)] or [[]]


def _ol_cover(c, title, nth, ctx) -> list[str]:
    m = c["meta"]
    return [
        f"- 主标题：{m['topic']}",
        f"- 口径条：{ctx['window']} · EDAT 口径 · 命中 {m['hit_count']} 篇",
    ]


def _ol_agenda(c, title, nth, ctx) -> list[str]:
    return [
        "- 01 检索策略 / 02 文献体量 / 03 来源期刊",
        "- 04 时间趋势 / 05 主题分布 / 06 代表文献",
        "- 07 研究问题与 PRISMA / 08 证据等级与收敛 / 09 研究空白",
    ]


def _ol_method(c, title, nth, ctx) -> list[str]:
    m, n = c["meta"], c["notes"]
    return [
        f"- 检索式：{m['query'] or '(未记录)'}",
        f"- 时间窗口：{ctx['window']}",
        f"- 日期字段：{m['date_field']}",
        f"- 口径说明：{n['date_field']}",
        "- 执行顺序：先完成系统综述（纳入标准→证据底座→综述成文），"
        "再由综述产出 deck；本大纲中的综述页与综述正文同源。",
    ]


def _ol_kpi(c, title, nth, ctx) -> list[str]:
    return [f"- {k['label']}：{k['value']} {k['unit']}（{k['note']}）" for k in c["kpis"]]


def _ol_journals(c, title, nth, ctx) -> list[str]:
    return [f"- {j['name']} — {j['count']} 篇（{j['share']}%）" for j in c["journals"]]


def _ol_trend(c, title, nth, ctx) -> list[str]:
    return [f"- {y['year']}：{y['count']} 篇" for y in c["years"]]


def _ol_topics(c, title, nth, ctx) -> list[str]:
    n = c["notes"]
    out = []
    for t in c["topics"]:
        tag = ("（核心词桶：覆盖 ≥80%，源自检索式核心词，不构成分布信号）"
               if t.get("scope") == "core" else "")
        out.append(f"- {t['key']} — {t['count']} 篇（{t['share']}%）{tag}")
    out.append(f"- 口径：{n['bucketing']}")
    out.append("- 绘图要求：分布图只呈现非核心词桶；核心词桶以脚注说明，不进入图形。")
    return out


def _ol_cards(c, title, nth, ctx) -> list[str]:
    chunks = _article_chunks(c)
    chunk = chunks[min(nth - 1, len(chunks) - 1)]
    return [f"- PMID {a['pmid']}｜{a['journal']}（{a['year'] or 'n.d.'}）｜{a['title']}"
            f"｜入选理由：{a['reason']}" for a in chunk] or ["- （无代表文献）"]


def _ol_duo(c, title, nth, ctx) -> list[str]:
    return ["- 依 M08 分桶取占比最高的两个方向做左右对照",
            "- 每栏给出该方向的文献量、综述占比与外部验证占比",
            "- 综述占比 ≥95% 时须注明「该桶本身即按综述特征命中」，不构成独立信号"]


def _ol_outlook(c, title, nth, ctx) -> list[str]:
    n = c["notes"]
    return [
        "- 趋势判断：依据 M07 与 M08 数据得出，不得脱离数据",
        f"- 方法局限：{n['date_field']}；{n['bucketing']}",
        "- 下一步：补检同义词、扩展时间窗、精读代表文献、寻找外部验证",
    ]


def _ol_closing(c, title, nth, ctx) -> list[str]:
    m = c["meta"]
    return [
        f"- 本次检索在 {ctx['window']} 窗口内命中 {m['hit_count']} 篇文献，"
        "证据层结论见前部综述页。",
    ]


# --- review pages ---------------------------------------------------------
def _ol_picos(c, title, nth, ctx) -> list[str]:
    rv = ctx["rv"] or {}
    picos = (rv.get("meta") or {}).get("picos") or {}
    if not picos:
        return ["- PICOS 未随证据底座提供（缺 meta.picos）；"
                "该页将以占位符呈现，须带 --picos-file 重跑证据底座"]
    order = [("P", "population"), ("I", "index"), ("C", "comparator"),
             ("O", "outcome"), ("S", "study_type")]
    out = [f"- {k}：{picos.get(key, '（未提供）')}" for k, key in order]
    src = (rv.get("meta") or {}).get("picos_source")
    out.append(f"- 措辞来源：{src or '（未记录）'}")
    return out


def _ol_prisma(c, title, nth, ctx) -> list[str]:
    p = (ctx["rv"] or {}).get("prisma", {})
    out = [
        f"- 数据库检出 {p.get('identified', 0)} 篇",
        f"- 去重后 {p.get('records_screened', 0)} 篇",
        f"- 题录初筛排除 {p.get('excluded_screening_total', 0)} 篇",
        f"- 进入全文评估 {p.get('fulltext_assessed', 0)} 篇",
        f"- 潜在纳入（待全文复核）{p.get('eligible_pending_fulltext', 0)} 篇",
        f"- 已确认纳入 {p.get('included_confirmed', 0)} 篇",
    ]
    for e in (p.get("excluded_at_screening") or [])[:4]:
        out.append(f"- 排除原因｜{e['reason']}　{e['count']}")
    out.append("- 口径：筛选在题录与摘要层面由确定性规则执行，每条排除均登记原因，计数可复核。")
    return out


def _ol_levels(c, title, nth, ctx) -> list[str]:
    rv = ctx["rv"] or {}
    lv = rv.get("levels", [])
    total = sum(x["count"] for x in lv) or 1
    out = [f"- Level {x['level']}　{x['label']} — {x['count']} 篇"
           f"（{x['count'] / total * 100:.1f}%）" for x in lv]
    out.append("- 分级口径：由摘要中报告的研究设计推定，属暂定分级，须经全文复核确认。")
    return out


def _ol_convergence(c, title, nth, ctx) -> list[str]:
    conv = ((ctx["rv"] or {}).get("matrix") or {}).get("convergence", [])
    out = [f"- {x['theme']}｜支持 {x['support']}　Level I/II {x['high_level_rate']}%"
           f"　外部验证 {x['external_validation_rate']}%　强度 {x['strength']}"
           f"　置信度 {x['confidence']}" for x in conv]
    out.append("- 口径：收敛指标在全量潜在纳入文献池上计算，强度阈值以文献池自身基线自校准。")
    return out


def _ol_gaps(c, title, nth, ctx) -> list[str]:
    rv = ctx["rv"] or {}
    out = [f"- [{g.get('priority', '—')}] {g['type']}｜{g['gap']}｜{g['evidence']}"
           for g in (rv.get("gaps") or [])[:6]]
    try:
        import deck_build as db
        out += [f"- 议程：{t}" for t in db.gap_agenda(rv.get("gaps") or [])]
    except ImportError:
        pass
    return out


def _ol_quant(c, title, nth, ctx) -> list[str]:
    n = (ctx["rv"] or {}).get("numbers", {})
    rows = [
        ("auc_overall", "AUC / C-index（全部）"),
        ("auc_training", "AUC（训练集）"),
        ("auc_validation", "AUC（内部验证集）"),
        ("auc_external", "AUC（外部验证集）"),
        ("cohort_size", "队列规模（例）"),
    ]
    out = []
    for key, label in rows:
        st = n.get(key) or {}
        if not st.get("n"):
            continue
        dec = 0 if key == "cohort_size" else 3
        out.append(f"- {label}：n={st['n']}　中位 {st['median']:.{dec}f}　"
                   f"IQR {st['p25']:.{dec}f}–{st['p75']:.{dec}f}")
    out.append("- 口径：数值为「报告值」的分布，非合并效应量；多数摘要未报告置信区间。")
    return out


def _ol_findings(c, title, nth, ctx) -> list[str]:
    try:
        import deck_build as db
        return [f"- {head}｜{sub}" for _, head, sub in db.derived_findings(ctx["rv"] or {})]
    except ImportError:
        return ["- （需 deck_build.py 以派生核心发现）"]


def _ol_review_conclusion(c, title, nth, ctx) -> list[str]:
    rv = ctx["rv"] or {}
    p, n = rv.get("prisma", {}), rv.get("numbers", {})
    pool = p.get("eligible_pending_fulltext", 0) or 1
    conv = (rv.get("matrix") or {}).get("convergence", [])
    weak = [x["theme"] for x in conv if x.get("strength") in ("弱", "极弱", "空白")]
    auc = n.get("auc_overall") or {}
    out = [
        f"- 证据规模：潜在纳入 {p.get('eligible_pending_fulltext', 0)} 篇；"
        f"Level I {next((x['count'] for x in rv.get('levels', []) if x['level'] == 'I'), 0)} 篇",
        f"- 性能水平：AUC/C-index 中位 {auc.get('median', '—')}"
        f"（IQR {auc.get('p25', '—')}–{auc.get('p75', '—')}），训练集高于内部验证集",
        f"- 验证强度：外部验证率 {n.get('external_validation_n', 0) / pool * 100:.1f}%，"
        f"前瞻性 {n.get('prospective_n', 0) / pool * 100:.1f}%",
    ]
    out.append("- 薄弱方向：" + ("、".join(weak[:3]) + " 证据强度偏弱"
                                if weak else "各主题证据强度均衡"))
    out.append("- 结论边界：全文复核与 GRADE 评级完成前，不支持临床推荐强度的判定")
    return out


OUTLINE_BLOCKS = {
    "M01": _ol_cover, "M03": _ol_agenda, "M04": _ol_method, "M05": _ol_kpi,
    "M06": _ol_journals, "M07": _ol_trend, "M08": _ol_topics, "M09": _ol_cards,
    "M10": _ol_duo, "M11": _ol_outlook, "M12": _ol_closing,
    "M13": _ol_picos, "M14": _ol_prisma, "M15": _ol_levels,
    "M16": _ol_convergence, "M17": _ol_gaps, "M18": _ol_review_conclusion,
    "M19": _ol_quant, "M20": _ol_findings,
}

LAYER = {
    "M13": "综述层", "M14": "综述层", "M15": "综述层", "M16": "综述层",
    "M17": "综述层", "M18": "综述层", "M19": "综述层", "M20": "综述层",
}


def render_outline(c: dict) -> str:
    m, n = c["meta"], c["notes"]
    rv = c.get("review") or None
    window = f"{m['start_date'] or '不限'} 至 {m['end_date'] or '不限'}"
    limit = "不限" if not m["max_results"] else f"{m['max_results']} 篇"
    ctx = {"window": window, "rv": rv}

    seq = page_sequence(c)
    lines = [
        f"# {m['topic']}",
        "",
        "> 学术汇报 deck 大纲（自动生成，供 PPT 生成使用）",
        "",
        f"- 检索式：`{m['query'] or '(未记录)'}`",
        f"- 时间窗口：{window}",
        f"- 日期字段：{m['date_field']}",
        f"- 结果上限：{limit} ｜ 命中：{m['hit_count']} 篇",
        f"- 检索日期：{m['search_date']}",
        f"- 页数：{len(seq)}",
        ("- 综述层：已包含（先成文系统综述，再由综述派生本 deck；"
         "下方标注「综述层」的页面直接取自综述证据底座）"
         if rv else
         "- 综述层：**缺失**。本 deck 仅含描述性统计。请先完成系统综述，"
         "再带 --review 重跑 deck_content.py，否则交付给 PPT 环节的大纲不会包含综述内容。"),
        "",
        "---",
        "",
    ]

    nth: Counter = Counter()
    for layout, title in seq:
        nth[layout] += 1
        tag = LAYER.get(layout)
        heading = f"## {layout} · {title}" + (f"　【{tag}】" if tag else "")
        fn = OUTLINE_BLOCKS.get(layout)
        body = fn(c, title, nth[layout], ctx) if fn else [f"- （{title}）"]
        lines += [heading, *body, ""]

    lines += [f"_{n['source']}_", ""]
    return "\n".join(lines)


def write_outputs(content: dict, out_dir: str) -> tuple[str, str]:
    """Write deck_content.json and deck_outline.md. Returns both paths."""
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "deck_content.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, ensure_ascii=False, indent=2)

    md_path = os.path.join(out_dir, "deck_outline.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_outline(content))
    return json_path, md_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Build deck content model from a PubMed CSV.")
    ap.add_argument("--csv", required=True, help="Path to pubmed_results.csv")
    ap.add_argument("--out-dir", default=".", help="Output directory")
    ap.add_argument("--topic", default="", help="Report title (topic summary)")
    ap.add_argument("--query", default="", help="PubMed query string (inline)")
    ap.add_argument("--query-file", default=None, help="File containing the PubMed query")
    ap.add_argument("--start", default="", help="Start date YYYY/MM/DD")
    ap.add_argument("--end", default="", help="End date YYYY/MM/DD")
    ap.add_argument("--max-results", default=2000, type=int, help="Requested result ceiling")
    ap.add_argument("--max-articles", default=8, type=int, help="Max representative articles")
    ap.add_argument("--topics-file", default=None, help="JSON {name: regex} overriding default buckets")
    ap.add_argument("--review", default=None,
                    help="Path to review_evidence.json. Embeds the systematic-review layer into "
                         "deck_content.json and deck_outline.md so the deck -- and the PPT built "
                         "from this outline -- carries the review's own findings. Run the review "
                         "BEFORE this step: the review is the source, the deck is the rendering")
    ap.add_argument("--search-date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()

    content = build_content(args)
    json_path, md_path = write_outputs(content, args.out_dir)

    rv = content.get("review")
    print(f"[deck] content model -> {json_path}")
    print(f"[deck] outline       -> {md_path}")
    print(
        f"[deck] {content['meta']['hit_count']} records | "
        f"{len(content['journals'])} journals | {len(content['years'])} years | "
        f"{len(content['topics'])} topics | {len(content['articles'])} articles"
    )
    print(f"[deck] outline pages : {len(page_sequence(content))}"
          + (f"  (review layer: {', '.join(content['meta']['review_layers'])})"
             if rv else "  (descriptive layer only -- no review)"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

"""
Deck content model builder for pubmed-retrieve (Phase 5).

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

    return {
        "schema": SCHEMA,
        "meta": meta,
        "kpis": build_kpis(records, len(journal_counter), topics, years),
        "journals": journals,
        "years": years,
        "topics": topics,
        "articles": articles,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Markdown outline — the hand-off format for the .pptx pipeline.
# ---------------------------------------------------------------------------
def render_outline(c: dict) -> str:
    m, n = c["meta"], c["notes"]
    window = f"{m['start_date'] or '不限'} 至 {m['end_date'] or '不限'}"
    limit = "不限" if not m["max_results"] else f"{m['max_results']} 篇"

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
        "",
        "---",
        "",
        "## M01 · 封面",
        f"- 主标题：{m['topic']}",
        f"- 口径条：{window} · EDAT 口径 · 命中 {m['hit_count']} 篇",
        "",
        "## M03 · 目录",
        "- 01 检索策略 / 02 文献体量 / 03 来源期刊",
        "- 04 时间趋势 / 05 主题分布 / 06 代表文献",
        "",
        "## M04 · 检索策略",
        f"- 检索式：{m['query'] or '(未记录)'}",
        f"- 时间窗口：{window}",
        f"- 日期字段：{m['date_field']}",
        f"- 口径说明：{n['date_field']}",
        "",
        "## M05 · 文献体量",
    ]
    for k in c["kpis"]:
        lines.append(f"- {k['label']}：{k['value']} {k['unit']}（{k['note']}）")

    lines += ["", "## M06 · 来源期刊 Top 10"]
    for j in c["journals"]:
        lines.append(f"- {j['name']} — {j['count']} 篇（{j['share']}%）")

    lines += ["", "## M07 · 时间趋势"]
    for y in c["years"]:
        lines.append(f"- {y['year']}：{y['count']} 篇")

    lines += ["", "## M08 · 主题分布"]
    for t in c["topics"]:
        tag = "（核心词桶：覆盖 ≥80%，源自检索式核心词，不构成分布信号）" if t.get("scope") == "core" else ""
        lines.append(f"- {t['key']} — {t['count']} 篇（{t['share']}%）{tag}")
    lines.append(f"- 口径：{n['bucketing']}")
    lines.append("- 绘图要求：分布图只呈现非核心词桶；核心词桶以脚注说明，不进入图形。")

    lines += ["", "## M09 / M10 · 代表文献"]
    for a in c["articles"]:
        lines.append(f"- PMID {a['pmid']}｜{a['journal']}（{a['year'] or 'n.d.'}）｜{a['title']}｜入选理由：{a['reason']}")

    lines += [
        "",
        "## M11 · 趋势判断与局限",
        "- 趋势判断：依据 M07 与 M08 数据得出，不得脱离数据",
        f"- 方法局限：{n['date_field']}；{n['bucketing']}",
        "- 下一步：补检同义词、扩展时间窗、精读代表文献、寻找外部验证",
        "",
        "## M12 · 结论",
        f"- 本次检索在 {window} 窗口内命中 {m['hit_count']} 篇文献，主题分布与时间趋势见前。",
        "",
        f"_{n['source']}_",
        "",
    ]
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
    ap.add_argument("--search-date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()

    content = build_content(args)
    json_path, md_path = write_outputs(content, args.out_dir)

    print(f"[deck] content model -> {json_path}")
    print(f"[deck] outline       -> {md_path}")
    print(
        f"[deck] {content['meta']['hit_count']} records | "
        f"{len(content['journals'])} journals | {len(content['years'])} years | "
        f"{len(content['topics'])} topics | {len(content['articles'])} articles"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

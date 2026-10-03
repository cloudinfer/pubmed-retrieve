#!/usr/bin/env python3
"""Build a systematic-review evidence base from a PubMed results CSV.

This is the analysis layer of the review pipeline (Phase 5 of the
pubmed-retrieve skill). It turns a flat CSV of PubMed records into the
structured artefacts a PRISMA-style review needs:

  * PRISMA 2020 screening counts, computed deterministically from explicit,
    reproducible eligibility rules applied to title + abstract
  * provisional evidence grading on the 7-level pyramid (I-VII), derived from
    reported study design
  * quantitative signal extraction (AUC / C-index / hazard ratio / cohort size)
    with cohort tagging (training vs validation vs external)
  * a stratified representative corpus with a readable digest
  * a literature matrix (source x theme) and an evidence convergence summary
  * a rule-based knowledge-gap inventory

Methodological notes that shape the code, borrowed from the deep-research
methodology in academic-research-skills:

  * Every count must be reproducible: exclusion reasons are recorded, not
    silently dropped, so the PRISMA flow can be reconstructed and challenged.
  * Grading is always labelled provisional when it rests on an abstract: the
    abstract is a report of the study, not the study. Anything that needs full
    text (risk of bias, GRADE certainty) is emitted as a placeholder table for
    a human to complete, never filled in by inference.
  * Contradiction is only flagged when the abstract states it. "Contradicts"
    is never inferred from a merely weaker result.

Outputs: <out-dir>/review_evidence.json and <out-dir>/review_corpus.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deck_content as dc  # noqa: E402  (sibling module, import after path fix)

SCHEMA = "pubmed-review/1"

# ---------------------------------------------------------------------------
# Synthesis themes.
#
# These are NOT the same as deck_content.DEFAULT_TOPICS. The deck buckets are
# descriptive (what words appear); these are analytic (what claim the source
# bears on). A systematic review is organised around claims, not keywords, so
# the review gets its own theme file, overridable with --themes-file.
# ---------------------------------------------------------------------------
REVIEW_THEMES = {
    "方法与模型谱系": (
        r"radiomic|feature extraction|handcrafted|\bdeep learning\b|convolutional"
        r"|\bcnn\b|transformer|foundation model|machine learning|random forest"
        r"|xgboost|lasso|\bsvm\b|signature|nomogram"
    ),
    "预后与生存终点": (
        r"prognos|overall survival|disease-free|recurrence-free|\bpfs\b|\bos\b"
        r"|hazard ratio|survival analys|risk stratif|cox"
    ),
    "影像模态与序列": (
        r"\bct\b|computed tomograph|contrast-enhanced|\bmri\b|magnetic resonance"
        r"|\bpet\b|\bspect\b|ultrasound|contrast-enhanced ultrasound|\bceus\b"
        r"|dual-energy|gadoxetate|\bdwi\b|dynamic"
    ),
    "治疗场景与应答": (
        r"resection|hepatectom|ablation|\btace\b|transplant|immunotherap|targeted therap"
        r"|lenvatinib|sorafenib|atezolizumab|bevacizumab|chemotherap|radiotherapy"
        r"|treatment response|pathological response|\bmpr\b|downstaging"
    ),
    "验证与泛化能力": (
        r"external validation|multicent|multi-cent|multi-institution|generalizab"
        r"|prospective|real-world|calibration|discriminat|reproducib"
        r"|test cohort|validation cohort"
    ),
    "生物学关联与可解释性": (
        r"radiogenomic|genomic|transcriptom|proteom|single-cell|microenvironment"
        r"|immune infiltrat|biomarker|biological|patholog|histolog|tertiary lymphoid"
    ),
}

# ---------------------------------------------------------------------------
# Study design detection -> 7-level evidence pyramid.
# Order matters: first match wins, highest level first. Title is trusted over
# abstract because "systematic review" in the title is a strong claim.
# ---------------------------------------------------------------------------
LEVEL_RULES = [
    ("I", r"systematic review|meta-analys|pooled analysis|meta-regression|umbrella review|evidence map"),
    # Bare "randomized" is not enough: radiomics abstracts use it for cohort
    # splits and for discussing trials they did not run. Require explicit
    # trial-level randomisation language.
    ("II", r"randomi[sz]ed controlled trial|randomi[sz]ed (?:phase|clinical|multicenter|multicentre|prospective) trial|\brct\b|double-?blind|placebo-?controlled|randomly (?:assigned|allocated) to (?:receive|undergo|either|the (?:treatment|intervention|control|study|experimental))"),
    ("III", r"propensity|non-randomi[sz]ed controlled|quasi-experimental|matched control|before-and-after|prospective comparative"),
    ("IV", r"\bcohort\b|case-control|retrospective|prospective|observational|nested case"),
    ("VI", r"case series|case report|pilot|feasibility|descriptive|cross-sectional|survey"),
    ("VII", r"editorial|comment|letter|expert opinion|consensus statement|guideline|perspective|review article|narrative review"),
]

LEVEL_LABEL = {
    "I": "系统综述 / Meta 分析",
    "II": "随机对照试验",
    "III": "非随机对照研究",
    "IV": "队列 / 病例对照研究",
    "V": "描述性研究系统综述",
    "VI": "单组描述性研究 / 病例系列",
    "VII": "专家意见 / 述评 / 指南",
}

# ---------------------------------------------------------------------------
# Eligibility screening (PRISMA). Applied to title + abstract only.
# Every disease-specific pattern lives in --criteria-file (required); nothing
# about any particular topic is hard-coded here. IDX_IN / OUT_IN below are
# topic-NEUTRAL method/outcome signals kept only as seeds for the criteria
# template -- screening itself reads whatever the criteria file provides.
# ---------------------------------------------------------------------------
IDX_IN = r"radiomic|radiogenomic|deep learning|machine learning|convolutional|\bcnn\b|artificial intelligence|\bai\b|nomogram|signature|texture analys|image feature"
OUT_IN = r"prognos|survival|recurrence|relapse|\bpfs\b|\bos\b|hazard ratio|risk stratif|outcome|predict"
NONRESEARCH = r"^(?:editorial|comment|correction|erratum|retraction|letter|reply|author reply|published erratum)"

# Generic exclusion-reason labels; overridable via the criteria file.
POP_LABEL = "目标人群"
OTHER_PRIMARY_LABEL = "非目标原发肿瘤（题名主导）"
IDX_LABEL = "影像组学或影像人工智能方法"
OUT_LABEL = "预后/诊断结局"

# Screening patterns -- set exclusively by load_criteria(). The run aborts in
# require_criteria() before screening whenever no criteria file was provided,
# so these placeholders never reach the screen loop as empty strings.
POP_IN = ""
POP_STRONG = ""
OTHER_PRIMARY = ""

# Provenance of the active criteria (basename of --criteria-file), recorded in
# review_evidence.json so every PRISMA count is auditable and reproducible.
CRITERIA_SOURCE = ""

BAR = "=" * 78

NEGATION = (
    r"\bno significant|\bnot significant|did not (?:improve|predict|show|achieve)|failed to"
    r"|poor performance|limited (?:value|utility)|no (?:added|incremental) value"
    r"|controversial|inconsistent|conflicting|unable to (?:validate|replicate)"
)

# ---------------------------------------------------------------------------
# Quantitative signals
# ---------------------------------------------------------------------------
AUC_RE = re.compile(
    r"(?:(?:auc|a-?uc)[\s\-–—:]*(?:of|was|=|:)?\s*(0?\.\d{2,4}|1\.0{1,4}))"
    r"|(?:(?:c-?index|c-?statistic|concordance index)[\s\-–—:]*(?:of|was|=|:)?\s*(0?\.\d{2,4}|1\.0{1,4}))"
    r"|(?:(0?\.\d{2,4}|1\.0{1,4})\s*(?:for the )?(?:auc|a-?uc|c-?index))",
    re.IGNORECASE,
)
HR_RE = re.compile(r"hazard ratio[\s\-–—:]*(?:of|was|=|:)?\s*(\d+\.?\d*)", re.IGNORECASE)
N_RE = re.compile(r"(?:\bn\s*=\s*(\d{2,5}))|(?:(\d{2,5})\s+(?:consecutive\s+)?patients)", re.IGNORECASE)
EXTERNAL_RE = re.compile(r"external validation|external (?:test|cohort)|multi-?cent(?:er|re)|multi-?institution", re.IGNORECASE)
PROSPECTIVE_RE = re.compile(r"\bprospective\b", re.IGNORECASE)

SENT_SPLIT = re.compile(r"(?<=[.;])\s+")
SIGNAL_KEYS = ("auc", "a-uc", "c-index", "c index", "hazard ratio", "hr", "conclusion",
               "conclusions", "result", "results", "predict", "sensitivity", "specificity")


def build_review_records(df: pd.DataFrame) -> list[dict]:
    records = dc.build_records(df)
    for rec in records:
        hay = f"{rec['title']} {rec['abstract']}".lower()
        rec["_hay"] = hay
        rec["has_abstract"] = bool(rec["abstract"]) and len(rec["abstract"]) >= 120
    return records


def norm_key(rec: dict) -> str:
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", rec.get("doi", "")).strip().lower()
    if doi:
        return "doi:" + doi
    return "ti:" + re.sub(r"[^a-z0-9]", "", rec["title"].lower())[:120]


# ---------------------------------------------------------------------------
# PRISMA screening
# ---------------------------------------------------------------------------
def screen(records: list[dict]) -> dict:
    identified = len(records)

    seen: dict[str, str] = {}
    dup_removed = 0
    after_dedup: list[dict] = []
    for rec in records:
        k = norm_key(rec)
        if k in seen:
            dup_removed += 1
            continue
        seen[k] = rec["pmid"]
        after_dedup.append(rec)

    excluded: Counter = Counter()
    screened: list[dict] = []
    for rec in after_dedup:
        hay = rec["_hay"]
        if re.search(NONRESEARCH, rec["title"].strip().lower()):
            excluded["非研究型文献（述评/更正/通信）"] += 1
            continue
        if not re.search(POP_IN, hay):
            excluded[f"人群不符：未涉及{POP_LABEL}"] += 1
            continue
        title_l = rec["title"].lower()
        if OTHER_PRIMARY and re.search(OTHER_PRIMARY, title_l) and not (
            POP_STRONG and re.search(POP_STRONG, title_l)
        ):
            excluded[f"人群不符：原发肿瘤非{OTHER_PRIMARY_LABEL}"] += 1
            continue
        if not re.search(IDX_IN, hay):
            excluded[f"干预/暴露不符：无{IDX_LABEL}"] += 1
            continue
        if not re.search(OUT_IN, hay):
            excluded[f"结局不符：无{OUT_LABEL}"] += 1
            continue
        screened.append(rec)

    # Full-text stage: without full text we can only mark what is assessable.
    # Records whose abstract is missing cannot be assessed at all; the rest are
    # "eligible pending full-text confirmation" rather than "included", because
    # PRISMA inclusion requires full-text judgement that this pipeline cannot
    # make. The review text must state this explicitly.
    fulltext_assessed = len(screened)
    no_abstract = sum(1 for r in screened if not r["has_abstract"])
    excluded["摘要缺失，题录层面无法评估"] = no_abstract
    eligible = [r for r in screened if r["has_abstract"]]

    return {
        "identified": identified,
        "duplicates_removed": dup_removed,
        "records_screened": len(after_dedup),
        "excluded_at_screening": [
            {"reason": k, "count": v} for k, v in excluded.most_common()
        ],
        "excluded_screening_total": int(sum(excluded.values())) - no_abstract,
        "fulltext_assessed": fulltext_assessed,
        "fulltext_excluded": no_abstract,
        "eligible_pending_fulltext": len(eligible),
        "included_confirmed": 0,
        "records": eligible,
    }


# ---------------------------------------------------------------------------
# Evidence grading
# ---------------------------------------------------------------------------
# Two false positives dominate radiomics abstracts and must be caught before
# design matching runs:
#   1. "randomly assigned to the training and validation cohorts" is a data
#      split, not treatment allocation. It is not an RCT.
#   2. A review that *discusses* RCTs is not itself an RCT.
TRAIN_SPLIT_RE = re.compile(
    r"randomly (?:assigned|allocated|divided|split|separated|classified)"
    r"[^.]{0,90}?(?:training|validation|test|development|internal|derivation)",
    re.IGNORECASE,
)
REVIEW_SELF_RE = re.compile(
    r"\bthis (?:narrative |systematic )?review\b|we review|in this review"
    r"|aim of this review|this review aims|review aims to"
    r"|\bnarrative review\b|we summarize the current",
    re.IGNORECASE,
)


def grade_level(rec: dict) -> str:
    title = rec["title"].lower()
    abstract = rec["abstract"].lower()
    # Level I (systematic review / meta-analysis) is checked first on both
    # fields: an explicit synthesis method outranks any other signal.
    for pat in (LEVEL_RULES[0][1],):
        if re.search(pat, title) or re.search(pat, abstract):
            return "I"
    # Self-identified reviews are expert synthesis, not primary evidence.
    if REVIEW_SELF_RE.search(title) or REVIEW_SELF_RE.search(abstract):
        return "VII"
    for level, pat in LEVEL_RULES[1:]:
        if re.search(pat, title):
            if level == "II" and (TRAIN_SPLIT_RE.search(title) or TRAIN_SPLIT_RE.search(abstract)):
                return "IV"
            return level
    for level, pat in LEVEL_RULES[1:]:
        if re.search(pat, abstract):
            if level == "II" and TRAIN_SPLIT_RE.search(abstract):
                return "IV"
            return level
    return "IV" if rec["has_abstract"] else "VI"


def is_negation(rec: dict) -> bool:
    return bool(re.search(NEGATION, rec["_hay"]))


# ---------------------------------------------------------------------------
# Quantitative signals
# ---------------------------------------------------------------------------
def extract_numbers(rec: dict) -> dict:
    text = f"{rec['title']}. {rec['abstract']}"
    aucs = []
    for m in AUC_RE.finditer(text):
        val = next((g for g in m.groups() if g), None)
        if val is None:
            continue
        try:
            f = float(val)
        except ValueError:
            continue
        if 0.5 <= f <= 1.0:
            aucs.append(f)
    hrs = []
    for m in HR_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        # The bare regex happily swallows sample sizes and percentages sitting
        # next to "hazard ratio"; a plausible HR is 0.1-20. Anything outside
        # that range is an extraction artefact, not an effect size.
        if 0.1 <= v <= 20.0:
            hrs.append(v)
    ns = []
    for m in N_RE.finditer(text):
        v = next((g for g in m.groups() if g), None)
        if v:
            try:
                ns.append(int(v))
            except ValueError:
                continue
    # Tag the cohort context a metric is reported in.
    sent_ctx = SENT_SPLIT.split(text)
    tagged = {"training": [], "validation": [], "external": []}
    for s in sent_ctx:
        vals = [float(next(g for g in m.groups() if g)) for m in AUC_RE.finditer(s)
                if next((g for g in m.groups() if g), None)]
        vals = [v for v in vals if 0.5 <= v <= 1.0]
        if not vals:
            continue
        low = s.lower()
        if EXTERNAL_RE.search(low):
            tagged["external"].extend(vals)
        elif "training" in low or "derivation" in low or "development" in low:
            tagged["training"].extend(vals)
        elif "validation" in low or "test" in low or "internal" in low:
            tagged["validation"].extend(vals)
    return {
        "auc": aucs,
        "hr": hrs,
        "n": ns,
        "auc_by_cohort": tagged,
        "external_validation": bool(EXTERNAL_RE.search(text)),
        "prospective": bool(PROSPECTIVE_RE.search(text)),
    }


def signal_sentences(rec: dict, limit: int = 3) -> list[str]:
    out = []
    for s in SENT_SPLIT.split(rec["abstract"]):
        low = s.lower()
        if any(k in low for k in SIGNAL_KEYS) and len(s) > 40:
            out.append(dc.truncate(s, 320))
        if len(out) >= limit:
            break
    if not out:
        out = [dc.truncate(rec["abstract"], 320)]
    return out


# ---------------------------------------------------------------------------
# Corpus selection
# ---------------------------------------------------------------------------
LEVEL_RANK = {"I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, "VI": 5, "VII": 6}


def score_for_selection(rec: dict, max_year: int) -> tuple:
    lvl = LEVEL_RANK.get(rec["level"], 9)
    recency = 0 if rec["year"] and rec["year"] >= max_year - 1 else (1 if rec["year"] and rec["year"] >= max_year - 3 else 3)
    ext = 0 if rec["numbers"]["external_validation"] else 2
    pros = 0 if rec["numbers"]["prospective"] else 1
    return (lvl, recency + ext + pros, -(rec["year"] or 0))


def select_corpus(records: list[dict], themes: dict[str, re.Pattern], size: int, per_theme: int) -> list[dict]:
    max_year = max((r["year"] or 0) for r in records) if records else 0
    ranked = sorted(records, key=lambda r: score_for_selection(r, max_year))

    chosen: list[dict] = []
    chosen_ids: set[str] = set()

    # Guarantee every theme has a minimum number of exemplars.
    for name, rx in themes.items():
        n = 0
        for rec in ranked:
            if rec["pmid"] in chosen_ids:
                continue
            if rx.search(rec["_hay"]):
                chosen.append(rec)
                chosen_ids.add(rec["pmid"])
                n += 1
            if n >= per_theme:
                break
    for rec in ranked:
        if len(chosen) >= size:
            break
        if rec["pmid"] in chosen_ids:
            continue
        chosen.append(rec)
        chosen_ids.add(rec["pmid"])

    chosen.sort(key=lambda r: (LEVEL_RANK.get(r["level"], 9), -(r["year"] or 0)))
    return chosen[:size]


# ---------------------------------------------------------------------------
# Literature matrix + convergence
# ---------------------------------------------------------------------------
def build_matrix(corpus: list[dict], pool: list[dict], themes: dict[str, re.Pattern]) -> dict:
    names = list(themes)
    rows = []
    for rec in corpus:
        cells = {}
        for name in names:
            rx = themes[name]
            if not rx.search(rec["_hay"]):
                cells[name] = "—"
            elif is_negation(rec) and rx.search(rec["_hay"]):
                # Only an explicit negative statement earns a contradiction
                # marker; a weak result alone never does.
                cells[name] = "△"
            else:
                cells[name] = "✓"
        rows.append(
            {
                "pmid": rec["pmid"],
                "label": f"{rec['first_author']} 等 {rec['year'] or 'n.d.'}",
                "year": rec["year"],
                "level": rec["level"],
                "journal": rec["journal"],
                "cells": cells,
            }
        )

    # Convergence is measured on the FULL eligible pool, not on the display
    # corpus. The corpus is deliberately enriched with Level I/II and
    # externally validated studies so it can carry the narrative; measuring
    # convergence on it would manufacture a flattering picture of the field
    # that the underlying literature does not support.
    def theme_hits(rec: dict, name: str) -> str:
        hay = rec.get("_hay") or f"{rec['title']} {rec['abstract']}".lower()
        if not themes[name].search(hay):
            return "—"
        return "△" if is_negation(rec) else "✓"

    # Self-calibrating thresholds: a theme is graded against the pool's own
    # baseline rather than against absolute counts, so the grading does not
    # silently drift when the corpus size changes.
    base_high = sum(1 for r in pool if r["level"] in ("I", "II")) / max(1, len(pool))
    base_ext = sum(1 for r in pool if r["numbers"]["external_validation"]) / max(1, len(pool))

    convergence = []
    for name in names:
        support = [r for r in pool if theme_hits(r, name) == "✓"]
        mixed = [r for r in pool if theme_hits(r, name) == "△"]
        lv = [r["level"] for r in support]
        high = sum(1 for x in lv if x in ("I", "II"))
        ext = sum(1 for r in support if r["numbers"]["external_validation"])
        net = len(support) - len(mixed)
        share = len(support) / max(1, len(pool)) * 100
        high_rate = high / max(1, len(support))
        ext_rate = ext / max(1, len(support))
        mixed_rate = len(mixed) / max(1, len(support) + len(mixed))

        # Strength is graded on evidence quality, not on raw volume: 60 weak
        # retrospective papers are not a "strong" finding, and calling them one
        # would be exactly the source-tier inflation the methodology warns about.
        if not support and not mixed:
            strength, conf = "空白", "—"
        elif len(mixed) >= 5 and mixed_rate >= 0.10:
            strength, conf = "争议", "中"
        elif high_rate >= base_high * 1.25 and ext_rate >= base_ext * 1.15:
            strength, conf = "强", "高"
        elif high_rate >= base_high * 0.8 and ext_rate >= base_ext * 0.9:
            strength, conf = "中", "中"
        elif len(support) >= 20:
            strength, conf = "弱", "低-中"
        else:
            strength, conf = "极弱", "低"
        convergence.append(
            {
                "theme": name,
                "support": len(support),
                "mixed": len(mixed),
                "net": net,
                "share": round(share, 1),
                "high_level_support": high,
                "high_level_rate": round(high_rate * 100, 1),
                "external_validation_support": ext,
                "external_validation_rate": round(ext_rate * 100, 1),
                "mixed_rate": round(mixed_rate * 100, 1),
                "pool_size": len(pool),
                "levels": sorted(set(lv)),
                "strength": strength,
                "confidence": conf,
            }
        )
    return {"themes": names, "rows": rows, "convergence": convergence}


# ---------------------------------------------------------------------------
# Gap inventory
# ---------------------------------------------------------------------------
def build_gaps(records: list[dict], matrix: dict) -> list[dict]:
    n = len(records) or 1
    ext = sum(1 for r in records if r["numbers"]["external_validation"])
    pros = sum(1 for r in records if r["numbers"]["prospective"])
    lvl1 = sum(1 for r in records if r["level"] == "I")
    lvl2 = sum(1 for r in records if r["level"] == "II")
    years = [r["year"] for r in records if r["year"]]
    gaps = [
        {
            "type": "方法学",
            "gap": "外部验证覆盖不足",
            "evidence": f"{ext} / {n} 篇（{ext / n * 100:.1f}%）报告外部验证或多中心设计",
            "implication": "模型跨机构泛化能力缺乏独立证据，训练集内性能可能被高估",
            "priority": "高" if ext / n < 0.3 else "中",
        },
        {
            "type": "方法学",
            "gap": "前瞻性设计稀少",
            "evidence": f"{pros} / {n} 篇（{pros / n * 100:.1f}%）为前瞻性研究",
            "implication": "证据以回顾性单中心为主，选择偏倚与时间偏倚难以排除",
            "priority": "高" if pros / n < 0.15 else "中",
        },
        {
            "type": "证据等级",
            "gap": "高等级证据占比有限",
            "evidence": f"Level I {lvl1} 篇（{lvl1 / n * 100:.1f}%），Level II {lvl2} 篇（{lvl2 / n * 100:.1f}%）",
            "implication": "GRADE 评级起点受限，多数推荐强度只能评为低或极低",
            "priority": "中",
        },
    ]
    if years:
        gaps.append(
            {
                "type": "时效性",
                "gap": "窗口边缘年份收录不完整",
                "evidence": f"入库年份跨度 {min(years)}-{max(years)}，末年受在线优先与补录影响",
                "implication": "末年计数不能等同于当年出版量，跨年比较应看趋势而非绝对值",
                "priority": "中",
            }
        )
    for c in matrix["convergence"]:
        if c["strength"] in ("极弱", "空白"):
            gaps.append(
                {
                    "type": "实证",
                    "gap": f"主题「{c['theme']}」证据稀薄",
                    "evidence": f"支持性文献 {c['support']} 篇，存疑 {c['mixed']} 篇",
                    "implication": "该方向尚不足以形成结论，属优先投入的研究空白",
                    "priority": "高",
                }
            )
    gaps.append(
        {
            "type": "地域",
            "gap": "作者单位国别未采集，地域分布无法定量",
            "evidence": "PubMed 题录未结构化提供国别字段，本次检索未做作者机构解析",
            "implication": "地域代表性空白需人工补充评估，不得由本流程臆断",
            "priority": "低",
        }
    )
    gaps.append(
        {
            "type": "理论",
            "gap": "影像特征与生物学机制的映射不足",
            "evidence": "放射组学特征的可解释性缺乏统一的生物学解释框架",
            "implication": "预测性能与临床可接受性之间存在解释鸿沟",
            "priority": "中",
        }
    )
    return gaps


# ---------------------------------------------------------------------------
# Aggregate quantitative summary
# ---------------------------------------------------------------------------
def summarize_numbers(records: list[dict]) -> dict:
    all_auc, ext_auc, val_auc, tr_auc, hrs, ns = [], [], [], [], [], []
    auc_reported = 0
    for rec in records:
        num = rec["numbers"]
        if num["auc"]:
            auc_reported += 1
            all_auc.extend(num["auc"])
        ext_auc.extend(num["auc_by_cohort"]["external"])
        val_auc.extend(num["auc_by_cohort"]["validation"])
        tr_auc.extend(num["auc_by_cohort"]["training"])
        hrs.extend(num["hr"])
        if num["n"]:
            ns.append(max(num["n"]))

    def stat(xs):
        if not xs:
            return None
        xs = sorted(xs)
        return {
            "n": len(xs),
            "median": round(statistics.median(xs), 3),
            "p25": round(xs[len(xs) // 4], 3),
            "p75": round(xs[len(xs) * 3 // 4], 3),
            "min": round(xs[0], 3),
            "max": round(xs[-1], 3),
        }

    cs = stat(ns)
    if cs:
        # 近似合计：各研究抽取的最大样本数直接相加。多臂 / 共用队列的研究
        # 可能重复计入，仅供量级参考，deck 展示时必须带上这一口径。
        cs["sum"] = int(sum(ns))

    return {
        "abstracts_reporting_auc": auc_reported,
        "auc_overall": stat(all_auc),
        "auc_training": stat(tr_auc),
        "auc_validation": stat(val_auc),
        "auc_external": stat(ext_auc),
        "hazard_ratio": stat(hrs),
        "cohort_size": cs,
        "external_validation_n": sum(1 for r in records if r["numbers"]["external_validation"]),
        "prospective_n": sum(1 for r in records if r["numbers"]["prospective"]),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def render_corpus_md(meta: dict, prisma: dict, levels: list[dict],
                     corpus: list[dict], numbers: dict, matrix: dict,
                     gaps: list[dict], themes: dict[str, re.Pattern]) -> str:
    L = []
    L.append(f"# 证据语料摘要 · {meta['topic']}")
    L.append("")
    L.append(f"- 检索式：`{meta['query']}`")
    L.append(f"- 时间窗：{meta['start_date']} – {meta['end_date']}（{meta['date_field']}）")
    L.append(f"- 检索日期：{meta['search_date']}｜检出 {prisma['identified']} 篇")
    L.append(f"- 题录初筛后纳入 {prisma['eligible_pending_fulltext']} 篇（待全文复核确认）")
    L.append("")
    L.append("## PRISMA 计数")
    L.append("")
    L.append("| 阶段 | 数量 |")
    L.append("|---|---|")
    L.append(f"| 数据库检出 | {prisma['identified']} |")
    L.append(f"| 去重后 | {prisma['records_screened']} |")
    for e in prisma["excluded_at_screening"]:
        L.append(f"| 排除：{e['reason']} | {e['count']} |")
    L.append(f"| 进入全文评估 | {prisma['fulltext_assessed']} |")
    L.append(f"| 摘要缺失无法评估 | {prisma['fulltext_excluded']} |")
    L.append(f"| 待全文复核（潜在纳入） | {prisma['eligible_pending_fulltext']} |")
    L.append(f"| 已确认纳入（需人工完成） | {prisma['included_confirmed']} |")
    L.append("")
    L.append("## 证据等级分布（基于摘要的暂定分级）")
    L.append("")
    L.append("| Level | 类型 | 篇数 | 占比 |")
    L.append("|---|---|---|---|")
    tot = sum(x["count"] for x in levels) or 1
    for x in levels:
        L.append(f"| {x['level']} | {x['label']} | {x['count']} | {x['count'] / tot * 100:.1f}% |")
    L.append("")
    L.append("## 定量信号汇总")
    L.append("")
    L.append(f"- 报告 AUC/C-index 的摘要：{numbers['abstracts_reporting_auc']} 篇")
    for key, name in (("auc_overall", "全部"), ("auc_training", "训练集"),
                      ("auc_validation", "验证集"), ("auc_external", "外部验证")):
        s = numbers[key]
        if s:
            L.append(f"- {name} AUC：n={s['n']}，中位 {s['median']}（P25–P75 {s['p25']}–{s['p75']}，范围 {s['min']}–{s['max']}）")
    if numbers["hazard_ratio"]:
        s = numbers["hazard_ratio"]
        L.append(f"- 风险比：n={s['n']}，中位 {s['median']}（范围 {s['min']}–{s['max']}）")
    if numbers["cohort_size"]:
        s = numbers["cohort_size"]
        L.append(f"- 队列规模：n={s['n']}，中位 {s['median']}（P25–P75 {s['p25']}–{s['p75']}）")
    L.append(f"- 外部验证/多中心：{numbers['external_validation_n']} 篇；前瞻性：{numbers['prospective_n']} 篇")
    L.append("")
    L.append("## 证据收敛汇总")
    L.append("")
    L.append(f"| 主题 | 支持（占比） | 存疑 | Level I/II | 外部验证 | 强度 | 置信度 |")
    L.append("|---|---|---|---|---|---|---|")
    for c in matrix["convergence"]:
        L.append(
            f"| {c['theme']} | {c['support']}（{c['share']}%） | {c['mixed']} | "
            f"{c['high_level_support']}（{c['high_level_rate']}%） | "
            f"{c['external_validation_support']}（{c['external_validation_rate']}%） | "
            f"{c['strength']} | {c['confidence']} |"
        )
    L.append("")
    L.append("> 收敛指标在全量待复核文献池上计算，不在精选语料上计算，以避免抽样偏倚。")
    L.append("")
    L.append("## 研究空白清单")
    L.append("")
    L.append("| 类型 | 空白 | 依据 | 影响 | 优先级 |")
    L.append("|---|---|---|---|---|")
    for g in gaps:
        L.append(f"| {g['type']} | {g['gap']} | {g['evidence']} | {g['implication']} | {g['priority']} |")
    L.append("")
    L.append(f"## 代表文献语料（{len(corpus)} 篇）")
    L.append("")
    for i, rec in enumerate(corpus, 1):
        L.append(f"### {i}. {rec['title']}")
        L.append("")
        L.append(
            f"- PMID {rec['pmid']}｜{rec['journal']}｜{rec['year'] or 'n.d.'}｜"
            f"Level {rec['level']}（{LEVEL_LABEL.get(rec['level'], '未定')}）"
        )
        tags = []
        if rec["numbers"]["external_validation"]:
            tags.append("外部验证/多中心")
        if rec["numbers"]["prospective"]:
            tags.append("前瞻性")
        if rec["numbers"]["auc"]:
            tags.append("AUC=" + ", ".join(f"{v:.3f}" for v in sorted(set(rec["numbers"]["auc"]))[:4]))
        if rec["numbers"]["hr"]:
            tags.append("HR=" + ", ".join(str(v) for v in sorted(set(rec["numbers"]["hr"]))[:3]))
        if rec["numbers"]["n"]:
            tags.append("N=" + str(max(rec["numbers"]["n"])))
        if tags:
            L.append("- 信号：" + "；".join(tags))
        hay = rec.get("_hay") or f"{rec['title']} {rec.get('abstract', '')}".lower()
        th = [k for k in themes if themes[k].search(hay)]
        if th:
            L.append("- 主题：" + "、".join(th))
        for s in rec["signals"]:
            L.append(f"  - {s}")
        L.append("")
    return "\n".join(L)


def build(args) -> dict:
    df = pd.read_csv(args.csv)
    records = build_review_records(df)

    themes_raw = load_themes(args.themes_file)
    themes = {k: re.compile(v, re.IGNORECASE) for k, v in themes_raw.items()}

    prisma = screen(records)
    eligible = prisma["records"]

    for rec in eligible:
        rec["level"] = grade_level(rec)
        rec["numbers"] = extract_numbers(rec)
        rec["signals"] = signal_sentences(rec)

    # deck_content.build_records drops the author column, so recover it here.
    df2 = df.copy()
    df2["Pmid"] = df2["Pmid"].astype(str).str.strip()
    first_by_pmid = {}
    for row in df2.to_dict("records"):
        a = dc.clean(row.get("Authors"))
        first_by_pmid[str(row["Pmid"])] = a.split(",")[0] if a else ""
    for rec in eligible:
        rec["first_author"] = first_by_pmid.get(rec["pmid"], "") or "匿名"

    level_counter = Counter(r["level"] for r in eligible)
    levels = [
        {"level": k, "label": LEVEL_LABEL.get(k, "未定"), "count": v}
        for k, v in sorted(level_counter.items(), key=lambda kv: (LEVEL_RANK.get(kv[0], 9), kv[0]))
    ]

    numbers = summarize_numbers(eligible)
    corpus = select_corpus(eligible, themes, args.corpus_size, args.per_theme)
    matrix = build_matrix(corpus, eligible, themes)
    gaps = build_gaps(eligible, matrix)

    def themes_of(rec: dict) -> list[str]:
        hay = rec.get("_hay") or f"{rec['title']} {rec['abstract']}".lower()
        return [k for k in themes if themes[k].search(hay)]

    pub = []
    for rec in corpus:
        pub.append(
            {
                "pmid": rec["pmid"],
                "title": rec["title"],
                "journal": rec["journal"],
                "year": rec["year"],
                "doi": rec["doi"],
                "first_author": rec["first_author"],
                "level": rec["level"],
                "level_label": LEVEL_LABEL.get(rec["level"], "未定"),
                "signals": rec["signals"],
                "numbers": {
                    "auc": sorted(set(rec["numbers"]["auc"])),
                    "hr": sorted(set(rec["numbers"]["hr"])),
                    "n": rec["numbers"]["n"],
                    "external_validation": rec["numbers"]["external_validation"],
                    "prospective": rec["numbers"]["prospective"],
                },
                "themes": themes_of(rec),
            }
        )

    meta = {
        "topic": args.topic,
        "query": dc.load_query(args.query_file, args.query),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "search_date": args.search_date,
        "date_field": "EDAT（PubMed 入库日期）",
        "max_results": args.max_results,
        "schema": SCHEMA,
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }

    return {
        "meta": meta,
        "prisma": {k: v for k, v in prisma.items() if k != "records"},
        "levels": levels,
        "numbers": numbers,
        "themes": list(themes_raw.keys()),
        "matrix": matrix,
        "gaps": gaps,
        "corpus": pub,
        "eligible_pmids": [r["pmid"] for r in eligible],
    }


def load_themes(path: str | None) -> dict[str, str]:
    if not path:
        return dict(REVIEW_THEMES)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data:
        raise SystemExit("--themes-file must be a non-empty JSON object of {name: regex}")
    return {str(k): str(v) for k, v in data.items()}


REQUIRED_CRITERIA_KEYS = ("pop_in", "idx_in", "out_in")


def load_criteria(path: str) -> None:
    """Load the eligibility criteria (screening regexes + reason labels).

    ``pop_in`` / ``idx_in`` / ``out_in`` are mandatory; ``pop_strong`` and
    ``other_primary`` default to empty (their checks are disabled); the four
    labels are optional. The path is validated by :func:`require_criteria`
    before this runs, so a missing file never reaches here.
    """
    global POP_IN, POP_STRONG, OTHER_PRIMARY, IDX_IN, OUT_IN
    global POP_LABEL, OTHER_PRIMARY_LABEL, IDX_LABEL, OUT_LABEL
    global CRITERIA_SOURCE
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"--criteria-file must be a JSON object: {path}")
    missing = [k for k in REQUIRED_CRITERIA_KEYS if not str(data.get(k, "")).strip()]
    if missing:
        raise SystemExit(
            f"--criteria-file 缺少必填键：{', '.join(missing)}"
            "（各键含义见 references/review-criteria.md，模板 criteria_template.json 已列出全部键）")
    POP_IN = str(data["pop_in"])
    POP_STRONG = str(data.get("pop_strong", "") or "")
    OTHER_PRIMARY = str(data.get("other_primary", "") or "")
    IDX_IN = str(data["idx_in"])
    OUT_IN = str(data["out_in"])
    for key, name in (("pop_label", "POP_LABEL"),
                      ("other_primary_label", "OTHER_PRIMARY_LABEL"),
                      ("idx_label", "IDX_LABEL"),
                      ("out_label", "OUT_LABEL")):
        if key in data:
            globals()[name] = str(data[key])
    CRITERIA_SOURCE = os.path.basename(path)


def write_criteria_template(path: str) -> str:
    """Drop an editable criteria skeleton next to the output so the caller can
    fill it in instead of guessing the key names."""
    tpl = {
        # Placeholders stay free of backslashes so the file stays readable once
        # JSON-escaped; short tokens must still get \b when you fill them in.
        "pop_in": "疾病名A|疾病 A 全称|常用缩写",
        "pop_strong": "题名中出现即可判定为目标人群的强信号（无则填 (?!) 表示永不匹配）",
        "other_primary": "其他原发肿瘤正则；无排除项则填空串",
        "idx_in": IDX_IN,
        "out_in": OUT_IN,
        "pop_label": "目标人群",
        "other_primary_label": "非目标原发肿瘤（题名主导）",
        "idx_label": IDX_LABEL,
        "out_label": OUT_LABEL,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tpl, fh, ensure_ascii=False, indent=2)
    return path


def require_criteria(topic: str, criteria_path: str | None, out_dir: str) -> None:
    """Refuse to screen without a topic-specific criteria file -- for every topic.

    The script ships **no** built-in screening criteria: the eligibility
    patterns exist only in ``--criteria-file``. A missing file is therefore a
    hard stop with an editable skeleton, never a silent default. (Earlier
    versions hardcoded hepatocellular-carcinoma regexes and only guarded
    "non-hepatic" topics by keyword sniffing -- which still let hepatic-looking
    topics run on stale rules. Sniffing is gone; the file is simply required.)
    """
    if criteria_path:
        if not os.path.exists(criteria_path):
            raise SystemExit(f"--criteria-file not found: {criteria_path}")
        return
    os.makedirs(out_dir, exist_ok=True)
    tpl = write_criteria_template(os.path.join(out_dir, "criteria_template.json"))
    sys.stderr.write(
        f"\n{BAR}\n"
        "[review_evidence] 已中止：未提供纳入判据文件 --criteria-file。\n"
        "\n"
        "脚本不内置任何主题的筛选判据（疾病专属正则只能来自判据文件），\n"
        "因此对任何主题都会在此中止，而不是带着缺失或错配的判据继续筛。\n"
        "\n"
        f"本次主题：{topic or '（未提供）'}\n"
        f"已生成模板：{tpl}\n"
        "\n"
        "请按主题填写后重跑：\n"
        f"  --criteria-file \"{tpl}\"\n"
        "\n"
        "字段定义、写法规范与完整示例见 references/review-criteria.md。\n"
        f"{BAR}\n"
    )
    sys.exit(2)


PICOS_KEYS = ("population", "population_in", "population_out", "index", "comparator",
              "outcome", "outcome_in", "outcome_out", "study_type", "keywords")


def write_picos_template(path: str) -> str:
    """Drop an editable PICOS skeleton next to the output."""
    tpl = {k: (f"<按本次主题改写：{k}>" if k != "keywords" else "<主题词1；主题词2；主题词3>")
           for k in PICOS_KEYS}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tpl, fh, ensure_ascii=False, indent=2)
    return path


def require_picos(picos_path: str | None, out_dir: str) -> None:
    """Refuse to build the evidence base without --picos-file (any topic).

    The PICOS wording travels in ``meta.picos`` and is the deck's M13 page's
    single source of truth; without the file the deck would have to invent a
    population. Missing file = hard stop with an editable skeleton.
    """
    if picos_path:
        if not os.path.exists(picos_path):
            raise SystemExit(f"--picos-file not found: {picos_path}")
        return
    os.makedirs(out_dir, exist_ok=True)
    tpl = write_picos_template(os.path.join(out_dir, "picos_template.json"))
    sys.stderr.write(
        f"\n{BAR}\n"
        "[review_evidence] 已中止：未提供 PICOS 措辞文件 --picos-file。\n"
        "\n"
        "脚本不内置任何主题的 PICO 措辞；meta.picos 又是 deck M13 页的唯一来源，\n"
        "缺失它等于让下游自行编造人群描述，因此对任何主题都会在此中止。\n"
        "\n"
        f"已生成模板：{tpl}\n"
        "\n"
        "请按主题填写后重跑：\n"
        f"  --picos-file \"{tpl}\"\n"
        "\n"
        "字段定义与完整示例见 references/review-criteria.md。\n"
        f"{BAR}\n"
    )
    sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a systematic-review evidence base from a PubMed CSV.")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--topic", default="")
    ap.add_argument("--query", default="")
    ap.add_argument("--query-file", default=None)
    ap.add_argument("--start", default="", dest="start_date")
    ap.add_argument("--end", default="", dest="end_date")
    ap.add_argument("--max-results", default=2000, type=int)
    ap.add_argument("--corpus-size", default=90, type=int, help="Representative corpus size")
    ap.add_argument("--per-theme", default=8, type=int, help="Minimum exemplars per theme")
    ap.add_argument("--themes-file", default=None, help="JSON {theme: regex} overriding synthesis themes")
    ap.add_argument("--criteria-file", default=None,
                    help="JSON with the topic-specific eligibility criteria "
                         "(pop_in/pop_strong/other_primary/idx_in/out_in + labels). "
                         "REQUIRED -- the script ships no built-in criteria; "
                         "see references/review-criteria.md")
    ap.add_argument("--picos-file", default=None,
                    help="JSON with the PICOS wording. Not used for screening here -- it is "
                         "recorded into meta.picos so downstream artifacts (in particular the deck's "
                         "PICOS page) cannot invent their own population. REQUIRED.")
    ap.add_argument("--search-date", default=__import__("datetime").date.today().isoformat())
    args = ap.parse_args()

    require_criteria(args.topic, args.criteria_file, args.out_dir)
    require_picos(args.picos_file, args.out_dir)
    load_criteria(args.criteria_file)
    query = args.query
    if not query and args.query_file and os.path.exists(args.query_file):
        with open(args.query_file, encoding="utf-8") as fh:
            query = fh.read().strip()

    with open(args.picos_file, encoding="utf-8") as fh:
        picos = json.load(fh)

    content = build(args)
    content.setdefault("meta", {})["criteria_source"] = CRITERIA_SOURCE
    # The PICOS wording travels with the evidence base. The deck's M13 page used
    # to hardcode its own (hepatocellular-carcinoma) rows, so a generic topic got
    # a deck that contradicted its own review; recording it here gives the deck a
    # single authoritative source instead of a second, drifting copy.
    if picos:
        content["meta"]["picos"] = picos
        content["meta"]["picos_source"] = os.path.basename(args.picos_file)
    content["meta"]["picos_available"] = bool(picos)
    os.makedirs(args.out_dir, exist_ok=True)

    json_path = os.path.join(args.out_dir, "review_evidence.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, ensure_ascii=False, indent=2)

    md_path = os.path.join(args.out_dir, "review_corpus.md")
    themes = {k: re.compile(v, re.IGNORECASE) for k, v in (load_themes(args.themes_file)).items()}
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_corpus_md(content["meta"], content["prisma"], content["levels"],
                                  content["corpus"], content["numbers"], content["matrix"],
                                  content["gaps"], themes) + "\n")

    print(f"[review] evidence -> {json_path}")
    print(f"[review] corpus   -> {md_path}")
    p = content["prisma"]
    print(f"[review] identified={p['identified']} dedup={p['duplicates_removed']} "
          f"screened_out={p['excluded_screening_total']} eligible={p['eligible_pending_fulltext']}")
    print(f"[review] corpus={len(content['corpus'])} themes={len(content['themes'])} gaps={len(content['gaps'])}")
    print(f"[review] criteria={CRITERIA_SOURCE} picos={os.path.basename(args.picos_file)}")


if __name__ == "__main__":
    main()

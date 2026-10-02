"""Compose a submission-ready systematic review skeleton from the evidence base.

Everything that can be derived deterministically from the CSV is written by this
script: reference list, PRISMA counts, evidence grading table, convergence table,
study-characteristics table, GRADE shell, PROBAST shell, declarations and all
four appendices. Only genuinely interpretive prose is left as a WRITE-BLOCK, each
carrying an explicit brief, a word budget and a closed list of PMIDs that must be
cited -- so the writing step is a constrained fill-in, never free invention.

Outputs
    review_draft.md        full skeleton, ready for the writing step
    review_references.md   Vancouver reference list built from CSV rows
    review_refmap.json     PMID -> citation number
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import pandas as pd

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

LEVEL_LABEL = {
    "I": "系统综述 / Meta 分析",
    "II": "随机对照试验",
    "III": "非随机对照研究",
    "IV": "队列 / 病例对照研究",
    "V": "描述性研究系统综述",
    "VI": "单组描述性研究 / 病例系列",
    "VII": "专家意见 / 述评 / 指南",
}

# Single source of truth for result-section table numbers. Captions, the PRISMA
# checklist cross-references and review_check.py all key off these, so a table
# can never be renumbered in one place and left stale in another.
T_PRISMA = 1
T_LEVELS = 2
T_CHARACTERISTICS = 3
T_PROBAST = 4
T_NUMBERS = 5
T_CONVERGENCE = 6
T_GRADE = 7
T_GAPS = 8
T_MAX = T_GAPS

PROBAST_DOMAINS = [
    ("研究对象 Participants", "纳入是否连续、数据来源是否贴近真实临床场景",
     "单中心回顾性、选择性纳入、排除标准与结局相关"),
    ("预测因子 Predictors", "影像采集与特征提取的定义、时序与一致性",
     "分割与特征提取由同一操作者完成、序列参数不统一"),
    ("结局 Outcome", "终点定义、判定是否盲法、随访是否充分",
     "终点判定未盲法、随访时间不足、失访未报告"),
    ("分析 Analysis", "样本量充足性、缺失数据处理、验证方式与校准报告",
     "仅内部验证、无外部验证、未报告校准、样本量过小"),
]

GRADE_FACTORS = ["偏倚风险", "不一致性", "间接性", "不精确性", "发表偏倚"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def fmt_date(raw: str) -> str:
    """'2026/09' -> '2026 Sep'; '2026/09/12' -> '2026 Sep 12'."""
    raw = norm(raw)
    m = re.match(r"(\d{4})/(\d{1,2})(?:/(\d{1,2}))?", raw)
    if not m:
        return raw
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    if not 1 <= mo <= 12:
        return str(y)
    out = f"{y} {MONTHS[mo - 1]}"
    return f"{out} {int(d)}" if d else out


def van_name(full: str) -> str:
    """'Mehrad Zare' -> 'Zare M';  'Benqi Zhao' -> 'Zhao B'.

    PubMed writes names in natural order; Vancouver wants surname first followed
    by given-name initials. The last token is treated as the surname.
    """
    parts = norm(full).split()
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    surname = parts[-1]
    initials = "".join(p[0].upper() for p in parts[:-1] if p)
    return f"{surname} {initials}"


def abbrev_authors(authors: str, limit: int = 6) -> str:
    parts = [p.strip() for p in norm(authors).split(",") if p.strip()]
    if not parts:
        return "Anon"
    out = [van_name(p) for p in parts[:limit]]
    if len(parts) > limit:
        out.append("et al")
    return ", ".join(out)


def clean_doi(raw: str) -> str:
    raw = norm(raw)
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", raw)


def vancouver(i: int, row: dict) -> str:
    title = norm(row.get("Title")).rstrip(".")
    line = f"{i}. {abbrev_authors(row.get('Authors'))}. {title}. "
    line += f"{norm(row.get('Journal')).rstrip('.')}. {fmt_date(row.get('Date'))}."
    doi = clean_doi(row.get("Doi"))
    if doi:
        line += f" doi:{doi}."
    line += f" PMID: {norm(row.get('Pmid'))}."
    return line


# --------------------------------------------------------------------------- #
# deterministic sections
# --------------------------------------------------------------------------- #
def build_references(csv_path: str, pmids: list[str]) -> tuple[list[str], dict[str, int]]:
    df = pd.read_csv(csv_path, dtype=str)
    df["Pmid"] = df["Pmid"].astype(str).str.strip()
    by_pmid = {r["Pmid"]: r for r in df.to_dict("records")}
    lines, mapping = [], {}
    n = 0
    for pmid in pmids:
        row = by_pmid.get(str(pmid))
        if row is None:
            continue
        n += 1
        mapping[str(pmid)] = n
        lines.append(vancouver(n, row))
    return lines, mapping


def prisma_table(prisma: dict) -> list[str]:
    ex = prisma.get("excluded_at_screening", [])
    rows = [
        "| 阶段 | 数量 |",
        "|---|---|",
        f"| 数据库检索识别记录 | {prisma['identified']} |",
        f"| 去重后记录 | {prisma['identified'] - prisma['duplicates_removed']} |",
        f"| 题录层面排除 | −{prisma['excluded_screening_total']} |",
    ]
    for item in ex:
        rows.append(f"| 　　{item['reason']} | {item['count']} |")
    rows += [
        f"| 进入全文评估 | {prisma['fulltext_assessed']} |",
        f"| 全文层面排除 | −{prisma['fulltext_excluded']} |",
        f"| 潜在纳入（待全文复核） | {prisma['eligible_pending_fulltext']} |",
        "| 最终确认纳入 | 待全文复核后确定 |",
    ]
    return rows


def level_table(levels: list[dict]) -> list[str]:
    rows = ["| 证据等级 | 研究设计 | 篇数 | 占比 |", "|---|---|---|---|"]
    total = sum(x["count"] for x in levels) or 1
    for x in levels:
        rows.append(
            f"| {x['level']} | {LEVEL_LABEL.get(x['level'], x.get('label', '—'))} | "
            f"{x['count']} | {x['count'] / total * 100:.1f}% |"
        )
    rows.append(f"| **合计** | — | **{total}** | **100.0%** |")
    return rows


def convergence_table(matrix: dict) -> list[str]:
    rows = [
        "| 主题 | 支持研究数 | 覆盖度 | Level I/II 支持 | 外部验证支持 | 收敛强度 | 置信度 |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in matrix["convergence"]:
        rows.append(
            f"| {c['theme']} | {c['support']} | {c['share']}% | "
            f"{c['high_level_support']}（{c['high_level_rate']}%） | "
            f"{c['external_validation_support']}（{c['external_validation_rate']}%） | "
            f"{c['strength']} | {c['confidence']} |"
        )
    return rows


def characteristics_table(corpus: list[dict], mapping: dict[str, int]) -> list[str]:
    rows = [
        "| # | 作者（年） | 国家 | 研究设计 | 样本量 | 影像模态 | 预测终点 | 模型方法 | 验证方式 | 证据等级 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rec in corpus:
        n = mapping.get(rec["pmid"], "?")
        nums = rec.get("numbers", {})
        cohort = nums.get("n") or []
        # ``n`` is a list of every number matched in the extraction context; the
        # cohort size is the largest. Rendering the list itself would emit
        # something like "[281]" and be misread as a citation marker.
        sample = max(cohort) if isinstance(cohort, list) and cohort else "—"
        val = "外部验证" if nums.get("external_validation") else (
            "前瞻性" if nums.get("prospective") else "内部验证")
        # ``signals`` holds raw abstract sentences, not extracted endpoints.
        # Rendering them here produced truncated sentence fragments in the
        # "预测终点" column, which read as data but were not. Endpoint, country,
        # design, modality and modelling method all require full-text reading,
        # so they stay as explicit "待提取" placeholders -- the same convention
        # used for the PROBAST and GRADE shells.
        rows.append(
            f"| [{n}] | {rec.get('first_author', '匿名')}（{rec.get('year') or '—'}） | 待提取 | "
            f"待提取 | {sample} | 待提取 | 待提取 | 待提取 | {val} | {rec.get('level')} |"
        )
    return rows


def probast_shell(corpus: list[dict], mapping: dict[str, int], size: int = 12) -> list[str]:
    head = "| # | " + " | ".join(d[0].split()[0] for d in PROBAST_DOMAINS) + " | 整体判定 |"
    rows = [head, "|" + "---|" * (len(PROBAST_DOMAINS) + 2)]
    for rec in corpus[:size]:
        n = mapping.get(rec["pmid"], "?")
        rows.append(f"| [{n}] | " + " | ".join(["待评估"] * len(PROBAST_DOMAINS)) + " | 待评估 |")
    return rows


def grade_shell(matrix: dict) -> list[str]:
    rows = ["| 主题 | 支持研究数 | " + " | ".join(GRADE_FACTORS) + " | 确定性等级 |",
            "|---|---|" + "---|" * (len(GRADE_FACTORS) + 1)]
    for c in matrix["convergence"]:
        rows.append(
            f"| {c['theme']} | {c['support']} | " + " | ".join(["待评估"] * len(GRADE_FACTORS))
            + " | 待评估（观察性起点：低） |"
        )
    return rows


def abstract_results(prisma: dict, levels: list[dict], matrix: dict, n_themes: int) -> str:
    """Build the Results paragraph of the structured abstract.

    Two traps are handled here:
    * level ranking must follow actual counts, not list order -- the tail of the
      level list is the smallest bucket, never 'the other main component';
    * a theme whose coverage exceeds 80% is a core-concept bucket carrying no
      discriminative signal, so the abstract reports the largest *informative*
      theme and flags the core bucket explicitly instead of selling it as a
      finding.
    """
    head = (
        f"共识别记录 {prisma['identified']} 条，去重后 "
        f"{prisma['identified'] - prisma['duplicates_removed']} 条，"
        f"题录层面排除 {prisma['excluded_screening_total']} 条，"
        f"{prisma['fulltext_assessed']} 条进入全文评估，全文层面排除 {prisma['fulltext_excluded']} 条，"
        f"{prisma['eligible_pending_fulltext']} 条满足潜在纳入条件（最终纳入须经全文复核确定）。"
    )
    top2 = sorted(levels, key=lambda x: -x["count"])[:2]
    lvl = "、".join(
        f"{LEVEL_LABEL.get(x['level'], x.get('label', '—'))}（{x['count']} 篇）" for x in top2
    )
    conv = matrix["convergence"]
    informative = [c for c in conv if c["share"] < 80.0]
    lead = informative[0] if informative else conv[0]
    theme_txt = (
        f"主题综合覆盖 {n_themes} 个方向，其中「{lead['theme']}」"
        f"的支持研究数最多（{lead['support']} 篇，覆盖度 {lead['share']}%，"
        f"收敛强度 {lead['strength']}）。"
    )
    core = [c for c in conv if c["share"] >= 80.0]
    if core:
        theme_txt += (
            f"「{'」「'.join(c['theme'] for c in core)}」覆盖度超过 80%，"
            f"属概念性核心维度而非可区分的研究方向，不作为主要发现解读。"
        )
    return head + f"证据等级分布以 {lvl}为主。" + theme_txt + "证据确定性待全文复核后评定。"
    rows = ["| 空白类型 | 具体空白 | 依据 | 优先级 |", "|---|---|---|---|"]
    for g in gaps:
        rows.append(f"| {g['type']} | {g['gap']} | {g['evidence']} | {g['priority']} |")
    return rows


NUM_LABEL = [
    ("auc_overall", "AUC / C-index（全部报告）"),
    ("auc_training", "AUC（训练集）"),
    ("auc_validation", "AUC（内部验证集）"),
    ("auc_external", "AUC（外部验证集）"),
    ("hazard_ratio", "风险比 HR"),
    ("cohort_size", "队列样本量"),
]


def numbers_table(numbers: dict) -> list[str]:
    rows = ["| 指标 | 报告研究数 | 中位数 | 四分位间距 | 范围 |",
            "|---|---|---|---|---|"]
    for key, label in NUM_LABEL:
        st = numbers.get(key)
        if not st or not st.get("n"):
            continue
        rows.append(
            f"| {label} | {st['n']} | {st['median']:.3f} | "
            f"{st['p25']:.3f}–{st['p75']:.3f} | {st['min']:.3f}–{st['max']:.3f} |"
        )
    rows.append(f"| 报告 AUC 的摘要数 | {numbers.get('abstracts_reporting_auc', 0)} | — | — | — |")
    rows.append(f"| 含外部验证的研究 | {numbers.get('external_validation_n', 0)} | — | — | — |")
    rows.append(f"| 前瞻性设计的研究 | {numbers.get('prospective_n', 0)} | — | — | — |")
    return rows
    rows = ["| 空白类型 | 具体空白 | 依据 | 优先级 |", "|---|---|---|---|"]
    for g in gaps:
        rows.append(f"| {g['type']} | {g['gap']} | {g['evidence']} | {g['priority']} |")
    return rows


def gaps_table(gaps: list[dict]) -> list[str]:
    rows = ["| 空白类型 | 具体空白 | 依据 | 优先级 |", "|---|---|---|---|"]
    for g in gaps:
        rows.append(f"| {g['type']} | {g['gap']} | {g['evidence']} | {g['priority']} |")
    return rows


def prisma_checklist() -> list[str]:
    rows = ["| # | PRISMA 2020 条目 | 报告位置 | 状态 |", "|---|---|---|---|"]
    items = [
        ("1", "题名标识为系统综述"), ("2", "结构化摘要"), ("3", "研究理由"),
        ("4", "研究目的（PICO）"), ("5", "纳入排除标准"), ("6", "信息来源"),
        ("7", "完整检索策略"), ("8", "筛选流程"), ("9", "数据提取流程"),
        ("10a", "数据条目：结局"), ("10b", "数据条目：其他变量"),
        ("11", "偏倚风险评估工具"), ("12", "效应量"), ("13a", "综合方法：合格性"),
        ("13b", "综合方法：数据准备"), ("13c", "综合方法：结果展示"),
        ("13d", "综合方法：结果合成"), ("13e", "综合方法：异质性"),
        ("13f", "综合方法：敏感性分析"), ("14", "报告偏倚评估"),
        ("15", "证据确定性评价"), ("16a", "筛选结果：流程图"),
        ("16b", "筛选结果：排除原因"), ("17", "纳入研究特征"),
        ("18", "纳入研究偏倚风险"), ("19", "单项研究结果"),
        ("20a", "合成结果：每项分析"), ("20b", "合成结果：异质性"),
        ("20c", "合成结果：敏感性"), ("20d", "合成结果：报告偏倚"),
        ("21", "报告偏倚结果"), ("22", "证据确定性结果"),
        ("23a", "讨论：主要发现"), ("23b", "讨论：局限性"),
        ("23c", "讨论：对实践的启示"), ("23d", "讨论：对未来研究的启示"),
        ("24", "方案与注册"), ("25", "资助"), ("26", "利益冲突"), ("27", "数据可得性"),
    ]
    # NOTE: every "表 N" below must match a caption actually emitted by compose().
    # The table numbers are owned by the ``T_*`` constants below -- do not inline
    # literals here, or the checklist silently drifts out of sync with the body
    # (this happened: PROBAST was cited as 表 2 while the body numbered it 表 3).
    loc = {
        "1": "题名", "2": "摘要", "3": "1.1", "4": "1.2", "5": "2.2", "6": "2.3",
        "7": "2.4 / 附录 B", "8": "2.5", "9": "2.6", "10a": "2.7", "10b": "2.7",
        "11": f"2.8 / 表 {T_PROBAST}", "12": "2.9", "13a": "2.10", "13b": "2.10", "13c": "2.10",
        "13d": "2.10", "13e": "2.10", "13f": "2.10", "14": "2.11", "15": "2.12",
        "16a": "3.1 / 图 1", "16b": f"3.1 / 表 {T_PRISMA}", "17": f"3.2 / 表 {T_CHARACTERISTICS}",
        "18": f"3.3 / 表 {T_PROBAST}",
        "19": f"3.4 / 表 {T_NUMBERS}", "20a": f"3.5 / 表 {T_CONVERGENCE}",
        "20b": "3.5", "20c": "3.5", "20d": "3.5",
        "21": "3.6", "22": f"3.7 / 表 {T_GRADE}", "23a": "4.1", "23b": "4.4", "23c": "4.3",
        "23d": "4.3", "24": "5.1", "25": "5.2", "26": "5.3", "27": "5.4",
    }
    for num, text in items:
        rows.append(f"| {num} | {text} | {loc.get(num, '—')} | 已报告 |")
    return rows


# --------------------------------------------------------------------------- #
# write blocks
# --------------------------------------------------------------------------- #
def block(name: str, brief: list[str], words: str, pmids: list[str], extra: str = "") -> str:
    lines = [f"<!-- WRITE-BLOCK: {name}",
             "任务：" + "；".join(brief),
             f"字数：{words}",
             "必引 PMID：" + (", ".join(pmids) if pmids else "（背景性表述，可引指南或教科书）")]
    if extra:
        lines.append(extra)
    lines.append("完成撰写后请整块删除本注释，只保留正文。-->")
    return "\n".join(lines)


def theme_pmids(corpus: list[dict], theme: str, limit: int = 6) -> list[str]:
    hits = [r for r in corpus if theme in r.get("themes", [])]
    hits.sort(key=lambda r: (-len(r.get("signals", [])), r.get("year") or 0))
    return [r["pmid"] for r in hits[:limit]]


# --------------------------------------------------------------------------- #
# compose
# --------------------------------------------------------------------------- #
DEFAULT_PICOS = {
    "population": "经病理或临床标准确诊的肝细胞癌患者，不限治疗方式",
    "population_in": "题名或摘要明确涉及肝细胞癌或肝脏原发肿瘤",
    "population_out": "原发肿瘤位于肝外；仅提及肝转移；仅出现 \"hepatocellular\" 作为蛋白或受体名称（如 EphA2 全称）",
    "index": "基于 CT / MRI / 超声 / PET 的影像组学或影像人工智能模型",
    "comparator": "传统临床病理模型、单一临床指标，或不同建模路径之间的比较",
    "outcome": "总体生存、无复发生存与早期复发、病理学标志物、治疗应答",
    "outcome_in": "生存、复发、病理学标志物、治疗应答中的至少一项",
    "outcome_out": "仅诊断或分期，无预后或应答终点",
    "study_type": "原始研究（含队列、病例对照）与系统综述 / Meta 分析",
    "keywords": "肝细胞癌；影像组学；人工智能；预后；系统综述",
}

# The wording above is hepatocellular-carcinoma-specific. Left in place on an
# unrelated topic it does not error -- it just prints a manuscript whose PICOS
# table, inclusion criteria and keywords describe a different disease.
# guard_picos() refuses that, and PICOS_SOURCE is recorded in the draft footer.
PICOS_SOURCE = "builtin-hepatocellular-carcinoma"
PICOS_IS_DEFAULT = True
LIVER_HINT = r"hepat|\bhcc\b|liver|hepatic|肝"
BAR = "=" * 78


def guard_picos(topic: str, picos: dict | None, allow_default: bool, out_dir: str) -> None:
    """Refuse to draft a non-hepatic review with the built-in HCC PICOS."""
    if not PICOS_IS_DEFAULT or allow_default:
        return
    if re.search(LIVER_HINT, f"{topic}\n{json.dumps(picos or {}, ensure_ascii=False)}".lower()):
        return
    os.makedirs(out_dir, exist_ok=True)
    tpl_path = os.path.join(out_dir, "picos_template.json")
    tpl = {k: (f"<按本次主题改写：{k}>" if k != "keywords" else "<主题词1；主题词2；主题词3>")
           for k in DEFAULT_PICOS}
    with open(tpl_path, "w", encoding="utf-8") as fh:
        json.dump(tpl, fh, ensure_ascii=False, indent=2)
    sys.stderr.write(
        f"\n{BAR}\n"
        "[review_compose] 已中止：正在用内置「肝细胞癌」PICOS 撰写非肝脏主题的综述。\n"
        "\n"
        "继续执行不会报错，但产出的 PICO 表、纳入标准与关键词会在描述另一种疾病\n"
        "（真实案例：一篇影像组学综述的骨架里出现「经病理或临床标准确诊的肝细胞癌\n"
        "患者」与 EphA2 受体，均与检索主题无关）。\n"
        "\n"
        f"本次主题：{topic or '（未提供）'}\n"
        f"已生成模板：{tpl_path}\n"
        "\n"
        "请填写后重跑：\n"
        f"  --picos-file \"{tpl_path}\"\n"
        "\n"
        "确需沿用内置标准（仅肝脏主题适用）时加 --allow-default-picos。\n"
        f"{BAR}\n"
    )
    sys.exit(2)


def compose(evidence: dict, refs: list[str], mapping: dict[str, int],
            topic: str, regno: str, picos: dict | None = None) -> str:
    P = dict(DEFAULT_PICOS)
    if picos:
        P.update({k: str(v) for k, v in picos.items() if v})
    meta = evidence["meta"]
    prisma = evidence["prisma"]
    corpus = evidence["corpus"]
    matrix = evidence["matrix"]
    themes = evidence["themes"]
    gaps = evidence["gaps"]
    numbers = evidence.get("numbers", {})

    L: list[str] = []

    # ---- title block ----
    L.append(f"# {topic}：一项系统综述")
    L.append("")
    L.append(f"<!-- WRITE-BLOCK: english-title")
    L.append("任务：给出英文题名，须含 \"a systematic review\"，"
             "并包含人群、暴露、比较、结局四要素，≤ 20 个实词")
    L.append("完成撰写后请整块删除本注释，只保留题名行。-->")
    L.append("**English title：** _待填写_")
    L.append("")
    L.append("**Running title：** _待填写（≤ 50 字符）_")
    L.append("")

    # ---- abstract ----
    L.append("## 摘要")
    L.append("")
    L.append("**背景（Background）：**")
    L.append(block("abstract-background",
                   ["说明目标疾病的临床问题与疾病负担",
                    "指出现有预后或疗效评估手段的局限",
                    "说明影像组学被提出的动机"],
                   "80–120 字", []))
    L.append("")
    L.append("**目的（Objectives）：**")
    L.append(block("abstract-objectives",
                   ["用一句话给出 PICO(S) 四要素",
                    "人群、指数检验、比较（若有）、结局必须明确"],
                   "60–90 字", []))
    L.append("")
    L.append("**方法（Methods）：**")
    L.append(
        f"系统检索 PubMed（检索日期 {meta['search_date']}，"
        f"日期口径 {meta['date_field']}，覆盖 {meta['start_date']}–{meta['end_date']}），"
        f"按 PRISMA 2020 流程进行题录与全文层面的双重筛选、双人独立提取（本研究由"
        f"单一研究者结合机器辅助完成，差异由规则化判据消解）。"
        f"采用 PROBAST 评价偏倚风险，采用 GRADE 评价证据确定性。"
        f"方案与注册见文末声明。"
    )
    L.append("")
    L.append("**结果（Results）：**")
    L.append(abstract_results(prisma, evidence["levels"], matrix, len(themes)))
    L.append("")
    L.append("**结论（Conclusions）：**")
    L.append(block("abstract-conclusions",
                   ["给出 1–2 条可执行判断", "必须写明证据边界与全文复核的必要性"],
                   "60–100 字", []))
    L.append("")
    L.append(f"**注册（Registration）：** {regno or '本综述未预先注册方案。'}")
    L.append("")
    L.append(f"**关键词：** {P['keywords']}")
    L.append("")
    L.append(block("keywords",
                   ["将上方候选词替换为经 MeSH 核对的主题词，并补至 5–8 个",
                    "保留中英对照形式"],
                   "—", [],
                   "提示：MeSH 主题词需在 NCBI MeSH 数据库核对后填写，不要直译自由词。"))
    L.append("")
    L.append("---")
    L.append("")

    # ---- 1 introduction ----
    L.append("## 1 引言")
    L.append("")
    L.append("### 1.1 研究背景与理由")
    L.append("")
    L.append(block("rationale",
                   ["目标疾病的流行病学与临床负担",
                    "现有预后/疗效评估手段及其局限",
                    "影像组学的方法学定位与提出动机",
                    "既往综述覆盖到什么、留下了什么缺口",
                    "明确说明本综述为什么现在有必要做"],
                   "500–700 字", [corpus[0]["pmid"]] if corpus else [],
                   "提示：疾病负担类数字应引指南或权威流行病学文献，不要用本次检索的文献充当。"))
    L.append("")
    L.append("### 1.2 研究目的")
    L.append("")
    L.append("本综述旨在系统评价影像组学在目标人群预后与治疗应答预测中的研究现状、"
             "方法学质量与证据确定性，并识别研究空白。研究问题按 PICO(S) 表述如下：")
    L.append("")
    L.append("| 要素 | 内容 |")
    L.append("|---|---|")
    L.append(f"| 人群（P） | {P['population']} |")
    L.append(f"| 指数检验（I） | {P['index']} |")
    L.append(f"| 比较（C） | {P['comparator']} |")
    L.append(f"| 结局（O） | {P['outcome']} |")
    L.append(f"| 研究类型（S） | {P['study_type']} |")
    L.append("")
    L.append(block("objectives-narrative",
                   ["把上表转写成连贯段落",
                    "说明预期的读者与实践意义"],
                   "150–250 字", []))
    L.append("")
    L.append("---")
    L.append("")

    # ---- 2 methods ----
    L.append("## 2 方法")
    L.append("")
    L.append("本综述按 PRISMA 2020 报告，预测模型相关条目同时参照 TRIPOD 声明。")
    L.append("")
    L.append("### 2.1 方案与注册")
    L.append("")
    if regno:
        L.append(f"本综述方案已在 PROSPERO 注册，注册号 {regno}。")
    else:
        L.append("本综述未预先注册方案；检索式、筛选判据与综合方法在提取开始前已由脚本固化，"
                 "未作事后修改。")
    L.append("")
    L.append(f"纳入判据来源：`{PICOS_SOURCE}`"
             + ("（⚠ 内置肝细胞癌标准，仅在肝脏主题下适用）" if PICOS_IS_DEFAULT else "")
             + "。")
    L.append("")
    L.append("### 2.2 纳入与排除标准")
    L.append("")
    L.append("| 维度 | 纳入 | 排除 |")
    L.append("|---|---|---|")
    L.append(f"| 人群 | {P['population_in']} | {P['population_out']} |")
    L.append("| 指数检验 | 影像组学特征、影像人工智能或深度学习模型 | 仅常规影像定性判读，无定量特征提取 |")
    L.append(f"| 结局 | {P['outcome_in']} | {P['outcome_out']} |")
    L.append("| 研究类型 | 原始研究与系统综述 / Meta 分析 | 述评、更正、通信、会议摘要 |")
    L.append("| 语言与可及性 | 有英文题录与摘要 | 摘要缺失，题录层面无法评估 |")
    L.append("")
    L.append("### 2.3 信息来源")
    L.append("")
    L.append(f"检索 PubMed（NCBI E-utilities，esearch + efetch），检索执行日期 "
             f"{meta['search_date']}。未另行检索 Embase、Cochrane Library 或试验注册平台，"
             f"亦未进行手工补检与参考文献追溯——这是本综述已识别的检索覆盖局限，见 §4.4。")
    L.append("")
    L.append("### 2.4 检索策略")
    L.append("")
    L.append("检索式由概念块组合而成，每个概念块内以 `OR` 连接同义词，概念块之间以 `AND` 连接。"
             "按 PubMed 的规则，混用 `AND`/`OR` 时显式加括号以保证优先级。完整检索式如下：")
    L.append("")
    L.append("```")
    L.append(meta["query"])
    L.append("```")
    L.append("")
    L.append(f"日期限定：`{meta['start_date']}` 至 `{meta['end_date']}`（{meta['date_field']}）；"
             f"单次返回上限 {meta['max_results']} 条。")
    L.append("")
    L.append("> **口径说明**：本综述所有时间统计均基于 PubMed 入库日期（EDAT），"
             "而非期刊正式出版日期。入库量受在线优先出版、更正补录与数据库回溯收录影响，"
             "跨年比较应看趋势而非绝对量。")
    L.append("")
    L.append("### 2.5 文献筛选流程")
    L.append("")
    L.append("筛选分两级执行：先按题录（题名 + 摘要）判据做确定性排除，"
             "再由研究者对进入全文评估的记录做人工复核。题录层面的排除判据以正则规则固化，"
             "同一输入必得同一输出，可复现。全文层面的纳入判定、"
             "以及所有偏倚风险与确定性评价，均需人工完成。")
    L.append("")
    L.append("### 2.6 数据提取流程")
    L.append("")
    L.append("先由脚本从题录抽取作者、年份、期刊、DOI、PMID、摘要，"
             "并派生研究设计归类、影像模态、终点类型与定量信号；"
             "再由研究者按 CHARMS 框架补充国家、样本量、随访时长、"
             "分割方式、特征数量、建模算法、验证方式与校准指标。")
    L.append("")
    L.append("### 2.7 数据条目")
    L.append("")
    L.append("**结局指标**：总体生存（OS）、无复发生存（RFS）与早期复发、"
             "微血管侵犯（MVI）、血管包绕肿瘤细胞巢（VETC）、三级淋巴结构、Ki-67 与 CK19 等病理学标志物、"
             "以及治疗应答。效应量以 AUC / C-index 与风险比（HR）为主。")
    L.append("")
    L.append("**其他变量**：研究设计、样本量、影像模态、分割策略、"
             "感兴趣区范围（瘤内 / 瘤周 / 联合）、验证方式（内部 / 外部 / 前瞻性）、"
             "是否报告校准。")
    L.append("")
    L.append("### 2.8 偏倚风险评估")
    L.append("")
    L.append("采用 PROBAST 的四域结构评价纳入研究的偏倚风险：")
    L.append("")
    L.append("| 域 | 评价要点 | 常见降级情形 |")
    L.append("|---|---|---|")
    for name, point, risk in PROBAST_DOMAINS:
        L.append(f"| {name} | {point} | {risk} |")
    L.append("")
    L.append("整体偏倚风险取四个域中的最差值。题录层面只能给出\"待评估\"占位，"
             "**不得以摘要推断填充判定结果**。")
    L.append("")
    L.append("### 2.9 效应量")
    L.append("")
    L.append("预测性能以 AUC 或 C-index 及其置信区间表示；生存关联以 HR 及其置信区间表示。"
             "由于纳入研究在人群、模态、终点与建模路径上异质性较高，"
             "本综述以叙述综合与结构化表格为主，未做跨研究的效应量合并。")
    L.append("")
    L.append("### 2.10 证据综合方法")
    L.append("")
    L.append("综合分三层推进：")
    L.append("")
    L.append("1. **主题分桶**：按预定义正则规则将每条记录归入一个或多个主题，"
             "允许交叉归类，故各主题占比之和大于 100%。")
    L.append("2. **证据矩阵与收敛汇总**：以文献 × 主题矩阵刻画覆盖，"
             "再按支持研究数、高等级证据占比与外部验证占比判定收敛强度"
             "（强 / 中 / 弱 / 极弱 / 争议）。")
    L.append("3. **空白识别**：从覆盖不足、方法学缺位、时效性、地域分布四个维度归纳研究空白。")
    L.append("")
    L.append("未做 Meta 合并；异质性通过分层描述（按模态、终点、验证方式）呈现。")
    L.append("")
    L.append("### 2.11 报告偏倚评估")
    L.append("")
    L.append("通过比较题录报告的性能指标分布与已发表综述的汇总值，"
             "定性评估小样本阴性结果未被报告的可能；未绘制漏斗图，"
             "因预测模型研究缺少统一的效应量尺度。")
    L.append("")
    L.append("### 2.12 证据确定性评价")
    L.append("")
    L.append("采用 GRADE 框架，从偏倚风险、不一致性、间接性、不精确性、发表偏倚五个维度降级，"
             "观察性证据起点为\"低\"。预测模型证据额外考察验证方式与校准报告完整性。")
    L.append("")
    L.append("---")
    L.append("")

    # ---- 3 results ----
    L.append("## 3 结果")
    L.append("")
    L.append("### 3.1 文献筛选结果")
    L.append("")
    L.append("**图 1　PRISMA 2020 文献筛选流程图**")
    L.append("")
    L.append("```")
    L.append(f"数据库检索识别 n = {prisma['identified']}")
    L.append(f"  去重后        n = {prisma['identified'] - prisma['duplicates_removed']}")
    L.append(f"  题录排除      n = {prisma['excluded_screening_total']}")
    for item in prisma.get("excluded_at_screening", []):
        L.append(f"    - {item['reason']}：{item['count']}")
    L.append(f"  全文评估      n = {prisma['fulltext_assessed']}")
    L.append(f"  全文排除      n = {prisma['fulltext_excluded']}")
    L.append(f"  潜在纳入      n = {prisma['eligible_pending_fulltext']}（待全文复核确定）")
    L.append("```")
    L.append("")
    L.append(f"**表 {T_PRISMA}　筛选计数明细**")
    L.append("")
    L += prisma_table(prisma)
    L.append("")
    L.append(block("results-selection-narrative",
                   ["用一段话解释最主要的两个排除原因意味着什么",
                    "说明题录筛选与全文筛选的口径差异"],
                   "200–300 字", []))
    L.append("")
    L.append("### 3.2 纳入研究特征")
    L.append("")
    L.append(f"潜在纳入记录 {prisma['eligible_pending_fulltext']} 条，"
             f"证据等级分布见下表。其中 {len(corpus)} 篇构成本综述的引证样本"
             f"（按证据等级优先、兼顾各主题覆盖度抽取）。")
    L.append("")
    L.append(f"**表 {T_LEVELS}　证据等级分布**")
    L.append("")
    L += level_table(evidence["levels"])
    L.append("")
    L.append(f"**表 {T_CHARACTERISTICS}　纳入研究基本特征**")
    L.append("")
    L += characteristics_table(corpus, mapping)
    L.append("")
    L.append("> 表中\"待提取\"字段需经全文复核后补齐（CHARMS 框架）。")
    L.append("")
    L.append(block("results-characteristics-narrative",
                   ["描述年份跨度与上升趋势",
                    "描述影像模态与终点的分布特征",
                    "指出样本量与单中心比例方面的观察"],
                   "300–450 字", [corpus[1]["pmid"], corpus[2]["pmid"]] if len(corpus) > 2 else []))
    L.append("")
    L.append("### 3.3 偏倚风险")
    L.append("")
    L.append(f"**表 {T_PROBAST}　PROBAST 偏倚风险评价（节选）**")
    L.append("")
    L += probast_shell(corpus, mapping)
    L.append("")
    L.append(block("results-rob-narrative",
                   ["说明题录层面无法完成偏倚评估的原因",
                    "给出已可识别的系统性风险信号（如外部验证比例低）"],
                   "250–400 字", []))
    L.append("")
    L.append("### 3.4 单项研究结果")
    L.append("")
    L.append(f"**表 {T_NUMBERS}　定量信号汇总（由题录自动抽取，需全文核对）**")
    L.append("")
    if numbers:
        L += numbers_table(numbers)
        L.append("")
    L.append("> 上表由摘要文本自动抽取，反映\"报告值\"的分布，"
             "非合并效应量；未报告置信区间的研究无法纳入区间分析。")
    L.append("")
    L.append(block("results-individual",
                   ["按模态或终点分组，逐组陈述报告的性能区间",
                    "指出性能报告的完整性与置信区间缺失情况"],
                   "400–600 字", []))
    L.append("")
    L.append("### 3.5 证据综合")
    L.append("")
    L.append(f"**表 {T_CONVERGENCE}　主题证据收敛汇总**")
    L.append("")
    L += convergence_table(matrix)
    L.append("")
    core = [c for c in matrix["convergence"] if c["share"] >= 80.0]
    if core:
        L.append("> **口径提示**："
                 + "、".join(f"「{c['theme']}」（{c['share']}%）" for c in core)
                 + "覆盖度超过 80%，属概念性核心维度，几乎所有纳入研究都涉及，"
                   "不具区分度，不应解读为\"该方向是研究热点\"。真正有区分意义的是"
                 + "、".join(f"「{c['theme']}」" for c in matrix["convergence"] if c["share"] < 80.0)
                 + "。各主题允许交叉归类，故覆盖度之和大于 100%。")
        L.append("")
    for idx, theme in enumerate(themes, start=1):
        L.append(f"#### 3.5.{idx} {theme}")
        L.append("")
        L.append(block(f"synthesis-{theme}",
                       [f"归纳 {theme} 方向的主流做法与技术路线",
                        "报告该方向的性能区间与验证方式",
                        "指出该方向内部的分歧或不一致",
                        "与其他方向做一句对照"],
                       "400–600 字", theme_pmids(corpus, theme)))
        L.append("")
    L.append(block("synthesis-crosscutting",
                   ["做跨主题的交叉综合：趋同点、分歧点、方法学共性问题",
                    "不要重复各主题已写过的内容"],
                   "400–600 字", []))
    L.append("")
    L.append("### 3.6 报告偏倚")
    L.append("")
    L.append(block("results-reporting-bias",
                   ["定性讨论性能指标分布所暗示的发表偏倚可能",
                    "说明未做漏斗图检验的原因"],
                   "150–250 字", []))
    L.append("")
    L.append("### 3.7 证据确定性")
    L.append("")
    L.append(f"**表 {T_GRADE}　GRADE 证据确定性概要**")
    L.append("")
    L += grade_shell(matrix)
    L.append("")
    L.append("> 表中各项须在全文复核后填写；观察性证据起点为\"低确定性\"。")
    L.append("")
    L.append("---")
    L.append("")

    # ---- 4 discussion ----
    L.append("## 4 讨论")
    L.append("")
    L.append("### 4.1 主要发现")
    L.append("")
    L.append(block("discussion-findings",
                   ["用 3–4 条要点概括核心发现",
                    "每条必须挂一个数字（支持研究数、覆盖度或占比）",
                    "不要重复结果章节的细节"],
                   "400–600 字", []))
    L.append("")
    L.append("### 4.2 与既有证据的比较")
    L.append("")
    L.append(block("discussion-comparison",
                   ["与已发表的同类综述或 Meta 分析比较",
                    "说明本综述的增量（时间窗更新、口径差异、主题更细）"],
                   "300–450 字", []))
    L.append("")
    L.append("### 4.3 临床与研究意义")
    L.append("")
    L.append(block("discussion-implications",
                   ["对临床实践的启示（谨慎表述，不越界）",
                    "对未来研究设计的建议"],
                   "300–450 字", []))
    L.append("")
    L.append("### 4.4 研究空白与展望")
    L.append("")
    L.append(f"**表 {T_GAPS}　研究空白清单**")
    L.append("")
    L += gaps_table(gaps)
    L.append("")
    L.append(block("discussion-gaps-narrative",
                   ["把上表转写为按优先级组织的叙述",
                    "每个空白给出一条可执行的研究建议"],
                   "400–600 字", []))
    L.append("")
    L.append("### 4.5 局限性")
    L.append("")
    L.append("本综述的局限性须明确声明以下几点：")
    L.append("")
    L.append("1. **仅基于题录与摘要**：研究设计归类、证据分级与定量信号均由摘要文本推断，"
             "未经全文核对，须在全文复核后更新。")
    L.append("2. **单库检索**：仅检索 PubMed，未覆盖 Embase、Cochrane Library 与试验注册平台，"
             "可能存在漏检。")
    L.append("3. **未做效应量合并**：因人群、模态、终点与建模路径异质性较高，"
             "仅作叙述综合与结构化汇总。")
    L.append("4. **偏倚风险与确定性未评定**：PROBAST 与 GRADE 表为待评估占位，"
             "不得用推断值填充。")
    L.append("5. **主题分桶可交叉归类**：同一研究可归入多个主题，故占比之和大于 100%，"
             "不可相加。")
    L.append("")
    L.append(block("discussion-limitations-extra",
                   ["补充本主题特有的局限性（如语言偏倚、地域集中）"],
                   "150–250 字", []))
    L.append("")
    L.append("### 4.6 结论")
    L.append("")
    L.append(block("conclusions",
                   ["3–4 句收束", "给出可执行判断", "明确证据边界"],
                   "200–300 字", []))
    L.append("")
    L.append("---")
    L.append("")

    # ---- 5 declarations ----
    L.append("## 5 声明")
    L.append("")
    L.append("### 5.1 方案与注册")
    L.append("")
    L.append(regno or "本综述未预先注册方案；检索式、筛选判据与综合方法在提取开始前已固化，"
                      "可应要求提供。")
    L.append("")
    L.append("### 5.2 资助")
    L.append("")
    L.append("本研究未接受任何公共、商业或非营利部门资助。")
    L.append("")
    L.append("### 5.3 利益冲突")
    L.append("")
    L.append("所有作者声明无利益冲突。")
    L.append("")
    L.append("### 5.4 数据可得性")
    L.append("")
    L.append(f"检索结果、证据底座（`review_evidence.json`）与引证样本"
             f"（`review_corpus.md`）随文提供；提取表可向通讯作者索取。"
             f"原始文献经 DOI 或 PMID 跳转出版商获取。")
    L.append("")
    L.append("### 5.5 作者贡献")
    L.append("")
    L.append("| 角色 | 内容 |")
    L.append("|---|---|")
    L.append("| 概念化与方法学 | 研究问题界定、PRISMA/PROBAST/GRADE 框架选择 |")
    L.append("| 检索与数据管理 | 检索式构造、检索执行、数据清洗与证据底座构建 |")
    L.append("| 证据综合 | 主题分桶、证据矩阵、收敛判定与空白识别 |")
    L.append("| 初稿撰写 | 各章节撰写 |")
    L.append("| 复核与把关 | 引用核验、数字核对、全文复核 |")
    L.append("")
    L.append("### 5.6 人工智能使用声明")
    L.append("")
    L.append("本综述在以下环节使用了人工智能辅助：检索式构造、"
             "题录层面的确定性筛选、研究设计与证据等级的暂定推断、"
             "定量信号抽取，以及初稿骨架与表格生成。"
             "所有数值、引用编号与参考文献条目均由脚本从原始题录直接生成或经作者逐条核对，"
             "偏倚风险与证据确定性评价未由人工智能推断填充。"
             "作者对全文内容的准确性与完整性负责。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 参考文献")
    L.append("")
    L += refs
    L.append("")
    L.append("---")
    L.append("")

    # ---- appendices ----
    L.append("## 附录 A　PRISMA 2020 核对表")
    L.append("")
    L += prisma_checklist()
    L.append("")
    L.append("## 附录 B　完整检索式")
    L.append("")
    L.append("```")
    L.append(meta["query"])
    L.append("```")
    L.append("")
    L.append(f"数据库：PubMed　检索日期：{meta['search_date']}　"
             f"时间窗：{meta['start_date']}–{meta['end_date']}（{meta['date_field']}）　"
             f"返回上限：{meta['max_results']}")
    L.append("")
    L.append("## 附录 C　引证样本清单")
    L.append("")
    L.append("| 编号 | PMID | 年份 | 期刊 | 证据等级 |")
    L.append("|---|---|---|---|---|")
    for rec in corpus:
        L.append(f"| [{mapping.get(rec['pmid'], '?')}] | {rec['pmid']} | {rec.get('year') or '—'} | "
                 f"{rec.get('journal', '')} | {rec.get('level')} |")
    L.append("")
    L.append("## 附录 D　偏倚风险与确定性逐条评估表")
    L.append("")
    L.append("全文复核后填写，格式如下（每篇研究一行）：")
    L.append("")
    L.append("| PMID | 研究对象 | 预测因子 | 结局 | 分析 | 整体偏倚 | GRADE 降级因素 | 确定性 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for rec in corpus[:20]:
        L.append(f"| {rec['pmid']} | | | | | | | |")
    L.append("")

    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compose a submission-ready systematic review skeleton.")
    ap.add_argument("--evidence", required=True, help="review_evidence.json")
    ap.add_argument("--csv", required=True, help="pubmed_results.csv")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--topic", default="", help="Override the topic")
    ap.add_argument("--regno", default="", help="PROSPERO registration number")
    ap.add_argument("--picos-file", default=None,
                    help="JSON overriding PICOS wording (population/index/comparator/outcome/study_type/"
                         "population_in/population_out/outcome_in/outcome_out/keywords)")
    ap.add_argument("--allow-default-picos", action="store_true",
                    help="Permit the built-in hepatocellular-carcinoma PICOS on a non-hepatic topic (normally refused)")
    args = ap.parse_args()

    global PICOS_SOURCE, PICOS_IS_DEFAULT
    picos = None
    if args.picos_file:
        with open(args.picos_file, "r", encoding="utf-8") as fh:
            picos = json.load(fh)
        PICOS_SOURCE = os.path.basename(args.picos_file)
        PICOS_IS_DEFAULT = False

    with open(args.evidence, "r", encoding="utf-8") as fh:
        evidence = json.load(fh)

    topic = args.topic or evidence["meta"]["topic"]
    guard_picos(topic, picos, args.allow_default_picos, args.out_dir)
    pmids = [r["pmid"] for r in evidence["corpus"]]
    refs, mapping = build_references(args.csv, pmids)

    os.makedirs(args.out_dir, exist_ok=True)
    draft = compose(evidence, refs, mapping, topic, args.regno, picos)

    draft_path = os.path.join(args.out_dir, "review_draft.md")
    with open(draft_path, "w", encoding="utf-8") as fh:
        fh.write(draft)

    refs_path = os.path.join(args.out_dir, "review_references.md")
    with open(refs_path, "w", encoding="utf-8") as fh:
        fh.write("## 参考文献\n\n" + "\n".join(refs) + "\n")

    map_path = os.path.join(args.out_dir, "review_refmap.json")
    with open(map_path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)

    blocks = draft.count("<!-- WRITE-BLOCK")
    print(f"[review] draft       -> {draft_path}")
    print(f"[review] references  -> {refs_path}  ({len(refs)} entries)")
    print(f"[review] refmap      -> {map_path}")
    print(f"[review] write blocks: {blocks}  (must reach 0 before submission)")
    print(f"[review] picos       <- {PICOS_SOURCE}"
          + ("  ⚠ 使用内置肝细胞癌标准" if PICOS_IS_DEFAULT else ""))


if __name__ == "__main__":
    main()

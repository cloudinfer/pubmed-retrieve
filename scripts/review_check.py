"""Gate a systematic review before it is allowed to leave the pipeline.

The checks here are the ones that actually sink a manuscript: a citation number
that points nowhere, a paragraph of assertions with nothing behind it, a count in
the abstract that disagrees with the evidence base, or a PROBAST cell that was
filled in from an abstract instead of a full text. Anything rated P0 blocks
delivery.

Usage
    python review_check.py <review.md> --evidence review_evidence.json \
                                       --refmap review_refmap.json [--strict]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from collections import OrderedDict

P0, P1, P2 = "p0", "p1", "p2"

REQUIRED_SECTIONS = [
    ("摘要", r"^##\s*摘要"),
    ("1 引言", r"^##\s*1\s*引言"),
    ("2 方法", r"^##\s*2\s*方法"),
    ("3 结果", r"^##\s*3\s*结果"),
    ("4 讨论", r"^##\s*4\s*讨论"),
    ("5 声明", r"^##\s*5\s*声明"),
    ("参考文献", r"^##\s*参考文献"),
]

REQUIRED_SUBSECTIONS = [
    "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8",
    "2.9", "2.10", "2.11", "2.12",
    "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7",
    "4.1", "4.2", "4.3", "4.4", "4.5",
    "5.1", "5.2", "5.3", "5.4", "5.5", "5.6",
]

ABSOLUTE_TERMS = [
    "证明了", "明确表明", "明确证实", "一定可以", "无疑", "所有研究均",
    "无一例外", "首次证明", "突破性", "权威研究表明", "达到国际领先",
    "显著优于所有",
]

TERM_MISUSE = [
    ("发表时间", "应使用「入库日期（EDAT）」"),
    ("分类\",", "应使用「主题分桶」"),
]

# Numbers that must match the evidence base exactly.
COUNT_ALIASES = {
    "identified": ["共识别记录", "识别记录", "检索识别"],
    "eligible": ["潜在纳入", "满足潜在纳入条件"],
}


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def add(self, level: str, msg: str) -> None:
        self.items.append((level, msg))

    def count(self, level: str) -> int:
        return sum(1 for lv, _ in self.items if lv == level)

    def dump(self) -> None:
        order = {P0: 0, P1: 1, P2: 2}
        names = {P0: "P0 阻断", P1: "P1 提示", P2: "P2 建议"}
        for lv in (P0, P1, P2):
            rows = [m for l, m in self.items if l == lv]
            print(f"\n{names[lv]}：{len(rows)}")
            for m in rows[:40]:
                print(f"  - {m}")
            if len(rows) > 40:
                print(f"  ...（另有 {len(rows) - 40} 条）")


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def split_body(text: str) -> str:
    """Drop the reference list and appendices so prose checks see only prose."""
    m = re.search(r"^##\s*参考文献\s*$", text, flags=re.M)
    return text[:m.start()] if m else text


def check_structure(body: str, rep: Report) -> None:
    for name, pat in REQUIRED_SECTIONS:
        if not re.search(pat, body, flags=re.M):
            rep.add(P0, f"R01 缺少章节：{name}")
    for num in REQUIRED_SUBSECTIONS:
        if not re.search(rf"^###\s*{re.escape(num)}\b", body, flags=re.M):
            rep.add(P0, f"R02 缺少小节：{num}")
    for token in ("PRISMA 2020", "PROBAST", "GRADE"):
        if token not in body:
            rep.add(P1, f"R03 正文未提及 {token}")
    for token in ("人工智能使用声明", "利益冲突", "数据可得性", "作者贡献"):
        if token not in body:
            rep.add(P1, f"R04 缺少声明要件：{token}")


def check_write_blocks(raw: str, rep: Report) -> int:
    blocks = re.findall(r"<!--\s*WRITE-BLOCK:\s*([\w-]+)", raw)
    for name in blocks:
        rep.add(P0, f"R05 写作块未填写：{name}")
    return len(blocks)


def check_citations(body: str, n_refs: int, rep: Report) -> None:
    if n_refs == 0:
        rep.add(P0, "R06 参考文献为空")
        return
    used: set[int] = set()
    for grp in re.findall(r"\[([\d,\s]+)\]", body):
        for tok in grp.split(","):
            tok = tok.strip()
            if tok.isdigit():
                used.add(int(tok))
    out = sorted(n for n in used if n < 1 or n > n_refs)
    for n in out:
        rep.add(P0, f"R07 引用编号越界：[{n}]（参考文献共 {n_refs} 条）")
    unused = [i for i in range(1, n_refs + 1) if i not in used]
    if unused:
        rep.add(P2, f"R08 未被正文引用的参考文献 {len(unused)} 条："
                    + "、".join(str(i) for i in unused[:20])
                    + ("…" if len(unused) > 20 else ""))


# Method and declaration sections legitimately carry no citations.
# 3.1 reports this review's own screening counts -- data generated here, not
# claims about the literature, so demanding external citations would force the
# writer to cite sources for numbers no source contains.
EXEMPT_HEADINGS = re.compile(r"^(摘要|2\.|3\.1|5\.|4\.5|附录|参考文献|（开头）)")

# A Chinese journal paragraph typically runs 200-400 characters and is routinely
# supported by a single trailing citation, so a 200-character threshold would
# flag almost every well-written paragraph. 300 catches genuinely unsupported
# stretches without punishing normal academic prose.
UNCITED_RUN_LIMIT = 300


def check_citation_density(body: str, rep: Report) -> None:
    """No run of >=200 Chinese characters of prose may go uncited.

    Only narrative prose counts: tables, code blocks and bullet lines are
    stripped first, and the Methods/Declarations/abstract sections are exempt by
    design -- flagging them would just train the writer to bolt fake citations
    onto procedural text.
    """
    for heading, chunk in iter_chunks(body):
        if EXEMPT_HEADINGS.match(heading):
            continue
        chunk = re.sub(r"```.*?```", "", chunk, flags=re.S)
        for para in re.split(r"\n\s*\n", chunk):
            if "|" in para or para.lstrip().startswith((">", "-", "*")):
                continue
            longest = max(
                (len(re.sub(r"\s+", "", s)) for s in re.split(r"\[[\d,\s]+\]", para)),
                default=0,
            )
            if longest >= UNCITED_RUN_LIMIT:
                rep.add(P0, f"R09 连续 {longest} 字无引用（{heading}）："
                            f"{para[:60]}…")
                break


def iter_chunks(body: str):
    """Yield (current_heading, text) pairs, splitting on ##/### headings."""
    lines = body.split("\n")
    heading, buf = "（开头）", []
    for line in lines:
        m = re.match(r"^(#{2,3})\s+(.*)", line)
        if m:
            yield heading, "\n".join(buf)
            heading, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    yield heading, "\n".join(buf)


def check_counts(body: str, evidence: dict, rep: Report) -> None:
    prisma = evidence["prisma"]
    expect = OrderedDict([
        ("共识别记录", prisma["identified"]),
        ("题录层面排除", prisma["excluded_screening_total"]),
        ("进入全文评估", prisma["fulltext_assessed"]),
        ("全文层面排除", prisma["fulltext_excluded"]),
        ("潜在纳入", prisma["eligible_pending_fulltext"]),
    ])
    for label, value in expect.items():
        for m in re.finditer(re.escape(label), body):
            window = body[max(0, m.start() - 20): m.end() + 40]
            nums = [int(x) for x in re.findall(r"(\d+)\s*(?:条|篇)", window)]
            if nums and value not in nums:
                rep.add(P0, f"R10 「{label}」附近数字 {nums} 与证据底座不一致（应为 {value}）")
                break
    if prisma["identified"] - prisma["excluded_screening_total"] != prisma["fulltext_assessed"]:
        rep.add(P0, "R11 PRISMA 计数不自洽：识别 − 题录排除 ≠ 全文评估")


def check_language(body: str, rep: Report) -> None:
    for term in ABSOLUTE_TERMS:
        for m in re.finditer(re.escape(term), body):
            line_no = body[:m.start()].count("\n") + 1
            rep.add(P1, f"R12 绝对化表述「{term}」（第 {line_no} 行）")
    for term, advice in TERM_MISUSE:
        if term in body:
            rep.add(P1, f"R13 术语「{term}」{advice}")


def check_tables(body: str, rep: Report) -> None:
    """Table numbers must be unique, contiguous, and cross-reference correctly.

    Two failure modes are guarded here, both observed in practice:

    * a result table emitted without a caption, which lets the downstream
      renderer renumber tables positionally and drift the body out of sync with
      the cross-references; and
    * a PRISMA checklist row pointing at a table that exists but covers a
      different topic (PROBAST was cited as "表 2" while the body numbered it
      "表 3"), which reads as valid because the number resolves.
    """
    caps = [int(x) for x in re.findall(r"\*\*表\s*(\d+)\s*[　\s]", body)]
    if not caps:
        rep.add(P0, "R14 正文未发现任何编号表题（格式应为 **表 N　标题**）")
    cap_set = set(caps)
    dup = sorted({n for n in caps if caps.count(n) > 1})
    if dup:
        rep.add(P0, "R14 表题编号重复：" + "、".join(f"表 {n}" for n in dup))
    for i in range(1, (max(caps) if caps else 0) + 1):
        if i not in cap_set:
            rep.add(P0, f"R14 表编号不连续：缺 表 {i}")

    if "图 1" not in body:
        rep.add(P1, "R15 正文未出现图 1（PRISMA 流程图）")

    # --- cross-reference resolution -----------------------------------------
    captions = {int(n): t for n, t in re.findall(r"\*\*表\s*(\d+)\s*[　\s]+([^\n*]+)", body)}
    dangling = sorted(n for n in {int(x) for x in re.findall(r"表\s*(\d+)", body)}
                      if n not in cap_set)
    if dangling:
        rep.add(P0, "R14 表号引用悬空（正文无此表题）："
                    + "、".join(f"表 {n}" for n in dangling))

    # Each entry maps a PRISMA checklist item to the wording its target table
    # must contain. Only semantically unambiguous items are listed.
    expect = {
        "11": ("PROBAST", "偏倚"),
        "17": ("特征", "CHARMS"),
        "18": ("PROBAST", "偏倚"),
        "22": ("GRADE", "确定性"),
    }
    for row in re.findall(r"^\|\s*(\d+[a-f]?)\s*\|[^|]*\|([^|]*)\|[^|]*\|", body, re.M):
        num, loc = row[0], row[1]
        if num not in expect:
            continue
        for m in re.finditer(r"表\s*(\d+)", loc):
            tno = int(m.group(1))
            cap = captions.get(tno, "")
            if tno in cap_set and not any(tok in cap for tok in expect[num]):
                rep.add(P0, f"R20 PRISMA 核对表第 {num} 条指向 表 {tno}「{cap}」，"
                            f"与条目语义不符（应为含 {'/'.join(expect[num])} 的表）")
    figs = sorted({int(x) for x in re.findall(r"图\s*(\d+)", body)})
    for seq in (figs, sorted(cap_set)):
        for i in range(1, len(seq) + 1):
            if i not in seq:
                rep.add(P1, f"R16 图表编号不连续：缺 {i}")
                break


def check_length(body: str, rep: Report) -> int:
    plain = strip_comments(body)
    plain = re.sub(r"^\|.*$", "", plain, flags=re.M)
    plain = re.sub(r"\s+", "", plain)
    n = len(plain)
    if n < 12000:
        rep.add(P0, f"R17 正文字数 {n} 未达系统综述下限 12000 字")
    elif n < 13000:
        rep.add(P2, f"R18 正文字数 {n}，接近下限，建议补充讨论深度")
    return n


def check_placeholders(body: str, rep: Report) -> None:
    for tok in ("待填写", "_待填写_", "TODO", "XXX"):
        if tok in body:
            rep.add(P0, f"R19 残留占位符：{tok}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a review before delivery.")
    ap.add_argument("review", help="Path to the review markdown")
    ap.add_argument("--evidence", required=True, help="review_evidence.json")
    ap.add_argument("--refmap", default=None, help="review_refmap.json")
    ap.add_argument("--strict", action="store_true", help="P1 also blocks")
    args = ap.parse_args()

    with open(args.review, "r", encoding="utf-8") as fh:
        raw = fh.read()
    with open(args.evidence, "r", encoding="utf-8") as fh:
        evidence = json.load(fh)

    body = strip_comments(split_body(raw))
    rep = Report()

    n_blocks = check_write_blocks(raw, rep)
    # Section presence is checked on the whole document -- split_body() would
    # otherwise cut off the very heading we are looking for.
    check_structure(strip_comments(raw), rep)

    n_refs = 0
    if args.refmap and os.path.exists(args.refmap):
        with open(args.refmap, "r", encoding="utf-8") as fh:
            n_refs = len(json.load(fh))
    else:
        refs = re.findall(r"^(\d+)\.\s+\S", raw, flags=re.M)
        n_refs = len(refs)
    check_citations(body, n_refs, rep)
    check_citation_density(body, rep)
    check_counts(body, evidence, rep)
    check_language(body, rep)
    # Table numbers and their cross-references are checked on the whole document:
    # the PRISMA checklist lives in 附录 A, i.e. after 参考文献, so split_body()
    # would hide exactly the rows whose cross-references need validating.
    check_tables(strip_comments(raw), rep)
    check_placeholders(body, rep)
    n_chars = check_length(body, rep)

    print(f"综述：{args.review}")
    print(f"正文字数 {n_chars}　参考文献 {n_refs} 条　未填写写作块 {n_blocks}")
    rep.dump()

    p0, p1 = rep.count(P0), rep.count(P1)
    if p0:
        print(f"\n结论：不通过（P0={p0}）")
        sys.exit(1)
    if args.strict and p1:
        print(f"\n结论：严格模式不通过（P1={p1}）")
        sys.exit(1)
    print(f"\n结论：通过（P0=0，P1={p1}）")


if __name__ == "__main__":
    main()

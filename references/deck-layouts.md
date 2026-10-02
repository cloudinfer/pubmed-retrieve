# 学术汇报 deck 锁定版式目录 · M01–M12

正文页只能从下表的 12 个具名版式中选择，**不得临时发明页面结构**。
新增版式必须同时改三处：`references/deck-layouts.md`、`assets/deck/template-medical.html`、`scripts/deck_validate.py`。

设计规范（色板、字号、网格、禁止清单）见 `references/deck-theme.md`。

---

## 0. 内容模型（`deck_content.json`）

`scripts/deck_content.py` 产出的 JSON 是**唯一数据源**，HTML 渲染器与 .pptx 流程共用。
所有字段名锁死，版本号写入 `schema`。

```jsonc
{
  "schema": "pubmed-deck/1",
  "meta": {
    "topic":        "radiomics 在肝细胞癌预后预测中的应用",   // 检索主题摘要，≤ 30 字
    "query":        "(...)[Title/Abstract] AND ...",          // 完整检索式
    "start_date":   "2021/01/01",
    "end_date":     "2026/10/02",                             // 空则记为「不限」
    "search_date":  "2026-10-02",
    "date_field":   "EDAT（PubMed 入库日期）",
    "max_results":  2000,                                     // 0 表示不限
    "hit_count":    1284,
    "generated_at": "2026-10-02T16:20:00"
  },
  "kpis":    [ { "label": "命中文献", "value": "1284", "unit": "篇", "note": "EDAT 口径" } ],   // 固定 4 条
  "journals":[ { "name": "Front Oncol", "count": 57, "share": 4.4 } ],                        // Top 10
  "years":   [ { "year": 2021, "count": 150 } ],                                              // 升序
  "topics":  [ { "key": "深度学习", "count": 420, "share": 32.7, "pattern": "...",
                 "scope": "specific",                  // specific | core（share ≥ 80% 判 core）
                 "review_count": 38, "share_review": 9.0, "validation_count": 21,
                 "latest_year": 2026, "top_journal": "Front Oncol",
                 "top_journal_count": 12 } ],          // 降序
  "articles":[ { "pmid": "41234567", "title": "...", "journal": "...", "year": 2025,
                 "topic": "深度学习", "reason": "系统综述" } ],                                 // ≤ 8 条
  "notes": {
    "date_field":  "命中按 EDAT 统计，与期刊正式出版月不完全一致。",
    "bucketing":   "主题分桶可多重归类，各桶占比之和大于 100%。",
    "source":      "数据来源：PubMed（NCBI E-utilities），检索日期 2026-10-02。"
  }
}
```

**所有 `notes` 必须在报告中出现**，这是科研汇报的底线要求。

---

## 1. 版式总表

| 编号 | 名称 | 底 | 核心视觉 | 主要数据槽位 |
|------|------|----|----------|--------------|
| M01 | Cover | 深蓝 | 大标题 + 检索口径条 | `meta` |
| M02 | Statement | 白 | 单句大字 | `meta.topic` |
| M03 | Agenda | 白 | 编号目录两栏 | 固定 6 项 |
| M04 | Method | 白 | 检索式代码块 | `meta.query` 等 |
| M05 | KPI Tower | 白 | 四栏数字塔 | `kpis` |
| M06 | Journal Rank | 白 | 横向条形 Top10 | `journals` |
| M07 | Year Trend | 白 | 折线趋势 | `years` |
| M08 | Topic Matrix | 白 | 主题分桶条 | `topics` |
| M09 | Literature Cards | 白 | 文献卡片列表 | `articles` |
| M10 | Duo Compare | 白 | 左右对照 | `topics` / `articles` |
| M11 | Outlook | 白 | 三段式 | `notes` |
| M12 | Closing | 深蓝 | 结论 + 落款 | `meta` |
| M13 | PICOS | 白 | 研究问题与 PICOS | `review_evidence.meta` |
| M14 | PRISMA Flow | 白 | 筛选流程漏斗 | `review_evidence.prisma` |
| M15 | Evidence Levels | 白 | 证据等级分布 | `review_evidence.levels` |
| M16 | Convergence | 白 | 证据收敛汇总 | `review_evidence.matrix.convergence` |
| M17 | Gaps & Agenda | 白 | 研究空白与议程 | `review_evidence.gaps` |
| M18 | Review Closing | 深蓝 | 综述结论 | `review_evidence` |

默认页序（无 review 时 8–11 页，启用 `--review` 时 14–18 页）：

```
无 review:
M01 → M03 → M04 → M05 → M06 → M07 → M08 → M09 → M10 → M11 → M12
        └────────────────── 白底区，hero 页仅首尾 ──────────────────┘

启用 --review:
M01 → M03 → M04 → M13 → M14 → M05 → M15 → M06 → M07 → M08
       → M09 → M10 → M16 → M17 → M11 → M18 → M12
```

**裁剪规则**：页数紧张时，按 `M10 → M02 → M03` 的顺序删。
`M01 / M04 / M05 / M06 / M12` 为核心页，**不可删**。
`M07` 与 `M08` 至少保留其一。

---

## 2. 逐版式契约

### M01 · Cover

- **底**：`--anchor` 满底；文字 `--paper`；`--anchor-2` 用于一条竖向色块或发丝。
- **结构**：
  - eyebrow（左上）：`文献调研报告` / 英文 `LITERATURE REVIEW`，字距 0.14em
  - `display` 主标题：`meta.topic`，最多 2 行
  - 副标题（`body`）：一行检索口径摘要，形如 `2021-01-01 至 2026-10-02 · EDAT 口径 · 命中 1284 篇`
  - 底部 1px 发丝线 + 三段元信息（`caption`）：检索日期 / 结果上限 / schema 版本
- **禁止**：封面不放 logo、不放配图、不放装饰图形；不显示页码与页脚。

### M02 · Statement

- **底**：`--paper`。**必须带页眉页脚**（与 M01 不同）。
- **结构**：`display` 单句，`grid-column: 1 / 14`；下方 1 条 `caption` 注脚。
- **用途**：把 `meta.topic` 提炼成一句可被验证的研究问题，或给出本次调研的核心判断。
- **禁止**：超过 40 字；出现第二个句子。

### M03 · Agenda

- **底**：`--paper`。
- **结构**：两栏各 3 项，每项 = 三位编号（`h3`、`--anchor`）+ 标题（`h3`）+ 一句说明（`body-s`）；
  项间用 1px 发丝线分隔。
- **固定 6 项**：`01 检索策略` `02 文献体量` `03 来源期刊` `04 时间趋势` `05 主题分布` `06 代表文献`。

### M04 · Method（检索策略）

- **底**：`--paper`。
- **左栏 `1/8`**：检索式，等宽字体，`--wash` 底 + 1px `--hairline` 边框，
  整体 `body-s`，**允许自动换行，不允许横向滚动**。
- **右栏 `8/17`**：三条口径，每条 = 标签（`eyebrow`）+ 值（`h3`）+ 注（`caption`）：
  1. 时间窗口 → `meta.start_date` – `meta.end_date`
  2. 日期字段 → `meta.date_field`，并附 `notes.date_field`
  3. 结果上限 → `meta.max_results` / 命中 `meta.hit_count`
- **强制**：`notes.date_field` 必须原文出现。

### M05 · KPI Tower

- **底**：`--paper`。
- **结构**：四栏等宽，每栏 = 数字（`kpi-l`，`--anchor`）+ 单位（`body-s`，`--ink-2`）
  + 标签（`eyebrow`，`--ink-2`）+ 注（`caption`，`--ink-3`）；
  栏间 1px 发丝线；数字底部对齐同一基线。
- **数据**：取 `kpis` 前 4 条；不足 4 条时用 `—` 占位，**不得少于 3 条**。

### M06 · Journal Rank

- **底**：`--paper`。
- **左 `1/12`**：横向条形图，Top 10 期刊。
  - 条形高 24px、间距 16px、`--anchor` 纯色、**无圆角无渐变**
  - 期刊名（`body-s`）左对齐占 1/5 宽，条形右端接数值（`body-s`，`tabular-nums`）
  - 条长按 `count` 线性映射，最长条不超过左栏宽度
- **右 `12/17`**：三条解读（`body-s`）：集中度、头部期刊特征、与主题的相关性判断。
- **注脚**：`notes.source`。

### M07 · Year Trend

- **底**：`--paper`。
- **结构**：折线图占 `1/17` 全幅，高 320px。
  - 折线 2px `--anchor`；节点 6×6 **直角方块**（不用圆点）
  - 基线 1px `--hairline`；不画纵向网格
  - 峰值年份与最近年份各标注一次（数值 + 年份，`caption`）
  - 横轴为年份，仅标首年、峰值年、末年
- **右侧或下方**：两条解读（`body-s`）：增长/回落判断、可能的成因（发文量 vs 技术周期）。
- **数据**：`years`；若仅 1 个年份，本条版式自动跳过并改用 M06。

### M08 · Topic Matrix

- **底**：`--paper`。
- **结构**：横向分桶条，按 `count` 降序，最多 8 个桶。
  - 每条 = 桶名（`body-s`，占 4 列）+ 横向条（`--anchor` 主桶 / `--anchor-2` 次桶 / `--anchor-3` 其余）+
    `count` 与 `share`（`tabular-nums`）
- **强制注脚**：`notes.bucketing`（占比之和 > 100%），字号 `caption`。
- **禁止**：把分桶画成饼图（互斥语义错误）。

### M09 · Literature Cards

- **底**：`--paper`。
- **结构**：2×2 网格，4 张卡片；每张卡片：
  - 顶部 1px 发丝线
  - 期刊 + 年份（`eyebrow`，`--ink-2`）
  - 标题（`body-s`，最多 3 行，超出截断加省略号）
  - 底部 PMID（`caption`，等宽，`--ink-3`）+ 入选理由（`caption`，`--anchor`）
- **单页最多 4 条**；`articles` 多于 4 条时拆成 M09 + M10，或后续走附录。
- **强制**：PMID 必须来自 CSV 实查（见 `SKILL.md` Phase 3.2），**不得凭印象填写**。

### M10 · Duo Compare

- **底**：`--paper`。
- **结构**：左右等分（`1/9`、`9/17`），中间 1px 发丝线。
  - 每栏 = 栏标题（`h2`）+ 引导句（`body-s`）+ 3 条要点（`body-s`）
  - 左栏用 `--anchor` 标题，右栏用 `--ink` 标题，形成主次
- **用途**：主题两强对照、方法学对照（综述 vs 原始研究）、
  或「本期结论 vs 待验证问题」。
- **禁止**：作为装饰性对照页；两栏必须有实质差异。

### M11 · Outlook

- **底**：`--paper`。
- **结构**：三栏（`1/6`、`6/12`、`12/17`），每栏 = 编号（`h3`，`--anchor`）
  + 标题（`h3`）+ 正文（`body-s`）。
  1. `趋势判断` —— 基于 M07/M08 的数据下判断，不得脱离数据
  2. `方法局限` —— **必须**包含 `notes.date_field` 与 `notes.bucketing` 两条
  3. `下一步` —— 3 条以内可执行动作（补检、扩窗、精读、外部验证）
- **强制**：底部通栏注脚写 `notes.source`。

### M12 · Closing

- **底**：`--anchor` 满底，文字 `--paper`。
- **结构**：`h1` 结论一句话（≤ 24 字）+ 一条 `body` 下一步说明
  + 底部发丝线 + 落款（检索日期 / 命中量 / 技能名）。
- **禁止**：不显示页码页脚；不放「谢谢观看」类空话。

### M13 · PICOS

- **底**：`--paper`。
- **左 `1/10`**：5 行 `kv`，P/I/C/O/S 每项 = 字母标签 + 中文定义。
- **右 `10/17`**：`eyebrow` 标题 + `body-s` 执行口径（数据库、时间窗、潜在纳入数、复核状态）。
- **必须**：写明「全文复核完成前」为未确认状态，不得把潜在纳入写为已纳入。

### M14 · PRISMA Flow

- **底**：`--paper`。
- **左 `1/11`**：6 步横向条形漏斗，从数据库检出递减至已确认纳入；
  条色由浅至深（潜在纳入用 `--anchor`），数值右对齐。
- **右 `11/17`**：主要排除原因 Top 5，每项原因 + 计数。
- **注脚**：筛选由确定性规则执行，每条排除记录可复核。

### M15 · Evidence Levels

- **底**：`--paper`。
- **左 `1/11`**：证据等级横向条形图，最多 7 级；
  条色按等级深浅（高等级 `--anchor`，低等级 `--hairline`）。
- **右 `11/17`**：核心事实 + 分级口径 + 下一步（PROBAST）。
- **强制**：标注「暂定分级」「全文复核后确认」。

### M16 · Convergence

- **底**：`--paper`。
- **结构**：表头行 + 6 个分析主题行；列 = 主题 / 支持数 / Level I/II 占比 / 外部验证占比 / 强度。
- **强度着色**：强/中用 `--anchor` 系，弱/极弱用 `--anchor-3` 浅蓝，**不用 `--alert` 装饰**。
- **注脚**：收敛指标在全量潜在纳入文献池上计算，不在精选语料上计算。

### M17 · Gaps & Agenda

- **底**：`--paper`。
- **左 `1/9`**：已识别空白清单（类型标签 + 空白描述 + 证据）。
- **右 `9/17`**：研究议程建议，深色块（`--anchor` 底 + `--paper` 字）编号 01–05。
- **禁止**：不得臆断地域代表性或基金来源等题录未提供的信息。

### M18 · Review Closing

- **底**：`--anchor` 满底，文字 `--paper`。
- **结构**：5 条结论（标签 + 一句话），与 M12 相比更强调综述层面的边界声明。
- **必须**：最后一条明确「全文复核与 GRADE 评级完成前，不支持临床推荐强度判定」。
- **禁止**：不显示页码页脚；不放「谢谢观看」。

---

## 3. 内容映射与写作规则

| 规则 | 说明 |
|------|------|
| 数字必须来自 CSV | 页面上任何数字都要能回溯到 `deck_content.json`，禁止估算或举例 |
| 不写绝对结论 | 用「提示」「倾向」「在本次检索范围内」，避免「证明了」「显著优于」 |
| 口径必须落字 | `notes` 三条注脚在 M04 / M06 / M08 / M11 中至少各出现一次 |
| 核心词桶不进图 | `scope: "core"` 的桶（占比 ≥ 80%，即检索式核心词的固有命中）只作脚注，不进分布图 |
| 边缘年份不作基线 | 首年文献量不足峰值 10% 时视为入库日期跨界样本，趋势判断须换基线并显式说明 |
| 术语统一 | 用「主题分桶」而非「分类」；用「入库日期（EDAT）」而非「发表时间」 |
| 文献不评价质量 | 无影响因子/引用数据时，不得写「高水平期刊」「重要研究」 |
| 单页一句话原则 | 每页只讲一件事，讲不完就拆页 |

---

## 4. 校验

```bash
python scripts/deck_validate.py output/deck.html
```

校验项与分级见 `references/deck-theme.md` 第 10 节。
**P0 必须为 0** 才可交付；P1 需逐条确认或显式豁免。

# 学术汇报 deck 锁定版式目录 · M01–M24

正文页只能从下表具名版式中选择，**不得临时发明页面结构**。
新增版式必须同时改三处：`references/deck-layouts.md`、`assets/deck/template-medical.html`、`scripts/deck_validate.py`。

设计规范（色板、字号、网格、禁止清单）见 `references/deck-theme.md`。

> **前置条件**：deck 是流水线的最后一环。先完成系统综述（Phase 5），
> 再由综述产出 deck（Phase 6）。综述层 M13–M20 全部读 `review_evidence.json`，
> 而交给 PPT 环节的 `deck_outline.md` 在 deck 阶段写出——
> 顺序颠倒会让 PPT 素材缺整层综述。

---

## 0. 内容模型（`deck_content.json`）

`scripts/deck_content.py` 产出的 JSON 是**唯一数据源**，HTML 渲染器与 .pptx 流程共用。
所有字段名锁死，版本号写入 `schema`。

```jsonc
{
  "schema": "pubmed-deck/2",
  "meta": {
    "topic":        "影像组学文献调研",                        // 检索主题摘要，≤ 30 字
    "query":        "(...)[Title/Abstract] AND ...",          // 完整检索式
    "start_date":   "2021/01/01",
    "end_date":     "2026/10/02",                             // 空则记为「不限」
    "search_date":  "2026-10-02",
    "date_field":   "EDAT（PubMed 入库日期）",
    "max_results":  2000,                                     // 0 表示不限
    "hit_count":    395,
    "review_source": "review_evidence.json",                  // 无综述层时为 null
    "review_layers": ["prisma", "levels", "matrix", "numbers", "gaps"],
    "generated_at": "2026-10-02T16:20:00"
  },
  "kpis":    [ { "label": "命中文献", "value": "395", "unit": "篇", "note": "EDAT 口径" } ],   // 固定 4 条
  "journals":[ { "name": "Front Oncol", "count": 57, "share": 4.4 } ],                       // Top 10
  "years":   [ { "year": 2026, "count": 395 } ],                                             // 升序
  "topics":  [ { "key": "深度学习", "count": 100, "share": 25.3, "pattern": "...",
                 "scope": "specific",                  // specific | core（share ≥ 80% 判 core）
                 "review_count": 38, "share_review": 9.0, "validation_count": 21,
                 "latest_year": 2026, "top_journal": "Front Oncol",
                 "top_journal_count": 12 } ],          // 降序
  // 分析维度四件套（M21–M24 的唯一数据源），结构与 topics 相同，
  // 由标题与摘要正则命中生成，可多重归类；scope=core 桶不进图。
  // 四组正则均可用 --patterns-file 按主题覆盖（见下）。
  "questions":    [ { "key": "预后与生存", "count": 63, "share": 31.8, "validation_count": 20, "scope": "specific" } ],
  "modalities":   [ { "key": "MRI", "count": 93, "share": 47.0, "validation_count": 30, "scope": "specific" } ],
  "pipelines":    [ { "key": "影像组学（手工特征）", "count": 131, "share": 66.2, "validation_count": 40, "scope": "specific" } ],
  "eval_methods": [ { "key": "AUC / C-index", "count": 115, "share": 58.1, "validation_count": 55, "scope": "specific" } ],
  // 代表文献卡片页（M09）已移除；articles 仅保留在 JSON 中供 PMID 回查与
  // 附录核对，deck 与 PPT 大纲不再渲染。
  "articles":[ { "pmid": "41234567", "title": "...", "journal": "...", "year": 2025,
                 "topic": "深度学习", "reason": "系统综述" } ],                                 // ≤ 8 条
  "notes": {
    "date_field":  "命中按 EDAT 统计，与期刊正式出版月不完全一致。",
    "bucketing":   "主题分桶可多重归类，各桶占比之和大于 100%。",
    "analysis_bucketing": "分析维度四件套同样由标题与摘要正则命中生成，可多重归类；覆盖 ≥80% 的桶不进分布图。",
    "source":      "数据来源：PubMed（NCBI E-utilities），检索日期 2026-10-02。"
  },
  // 以下块仅在 deck_content.py 带 --review 时出现，是 M13–M20 的唯一数据源。
  // 由 review_evidence.json 精简而来：只保留渲染器读到的字段，
  // 因此 deck_content.json 仍是「HTML deck 与 PPT 大纲共用的一份数据」。
  "review": {
    "meta":    { "picos": { "population": "...", "index": "...", "comparator": "...",
                            "outcome": "...", "study_type": "..." },
                 "picos_source": "picos_radiomics.json", "picos_available": true,
                 "criteria_source": "criteria_radiomics.json" },
    "prisma":  { "identified": 395, "eligible_pending_fulltext": 313, "included_confirmed": 0,
                 "excluded_at_screening": [ { "reason": "...", "count": 43 } ] },
    "levels":  [ { "level": "IV", "label": "队列 / 病例对照研究", "count": 224 } ],
    "numbers": { "auc_overall": { "n": 182, "median": 0.838, "p25": 0.771, "p75": 0.886 },
                 "cohort_size": { "n": 150, "median": 286, "sum": 51230 } },
    "gaps":    [ { "type": "方法学", "gap": "...", "evidence": "...",
                   "implication": "...", "priority": "中" } ],
    "matrix":  { "convergence": [ { "theme": "...", "support": 208, "net": 180,
                                    "high_level_rate": 9.6, "external_validation_rate": 60.1,
                                    "strength": "争议", "confidence": "中" } ] }
  }
}
```

**所有 `notes` 必须在报告中出现**，这是科研汇报的底线要求。
`--patterns-file` 接受 `{"questions": {...}, "modalities": {...}, "pipelines": {...},
"eval_methods": {...}}`，任意子集可省略（回退内置默认正则）；桶正则形态与
`--topics-file` 一致（`{"桶名": "正则"}`），短词一律加 `\b`。

> `review` 块缺失时，M13–M20 全部不渲染、`deck_outline.md` 顶部标注
> 「综述层：**缺失**」。这是合法但需在答复中说明的降级状态。

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
| M10 | Duo Compare | 白 | 左右对照 | `topics` |
| M11 | Outlook | 白 | 三段式 | `notes` |
| M12 | Closing | 深蓝 | 结论 + 落款 | `meta` |
| M13 | PICOS | 白 | 研究问题与 PICOS | `review_evidence.meta.picos` |
| M14 | PRISMA Flow | 白 | 筛选流程漏斗 | `review_evidence.prisma` |
| M15 | Evidence Levels | 白 | 证据等级分布 | `review_evidence.levels` |
| M16 | Convergence | 白 | 证据收敛汇总 | `review_evidence.matrix.convergence` |
| M17 | Gaps & Agenda | 白 | 研究空白与议程 | `review_evidence.gaps` |
| M19 | Review Quant | 白 | 数据规模与定量性能 | `review_evidence.numbers` |
| M20 | Review Findings | 白 | 综述核心发现 | `review_evidence`（现算，非字面量） |
| M18 | Review Closing | 深蓝 | 综述结论 | `review_evidence`（现算，非字面量） |
| M21 | Question Map | 白 | 临床问题图谱条形 | `questions` |
| M22 | Modality Mix | 白 | 数据模态分布条形 | `modalities` |
| M23 | Pipeline Mix | 白 | 技术路线分布条形 | `pipelines` |
| M24 | Eval Methods | 白 | 评价方法报告率条形 | `eval_methods` |

> **M09（代表文献卡片）已移除**：文献列表不进 deck，改为在 M21–M24 展示
> 分析性维度（临床问题、数据模态、技术路线、评价方法）。
> `articles` 字段仅保留在 JSON 里供 PMID 回查。综述文档侧同理：
> 证据等级分布表与 PROBAST 偏倚风险评价（节选）表不再出现在综述主文
> （见 `review_compose.py` 表号常量注释）。
>
> **综述层（M13–M20）必须由 `review_evidence.json` 派生，不得在渲染器里写死。**
> 这些页面曾是一批字符串字面量，换主题后仍输出旧主题的人群与终点
> （真实案例：影像组学 deck 的 PICOS 页显示「肝细胞癌患者」，
> 核心发现里出现「MVI 预测」「TACE 应答预测」）。
> M13 的人群描述取自 `meta.picos`——该字段由 `review_evidence.py --picos-file` 写入，
> 因此**先生成系统综述、再生成 deck** 是硬性前置条件。

页序（综述层按叙事位置**插入**描述层，不追加在末尾）：

```
无 review（纯描述性，11–14 页）:
M01 → M03 → M04 → M05 → M06 → M07 → M08
       → M21 → M22 → M23 → M24 → M10 → M11 → M12
        └────────────────── 白底区，hero 页仅首尾 ──────────────────┘

启用 review（18–22 页，本例 21 页）:
M01 → M03 → M04 → M13 → M14 → M05 → M15 → M06 → M07 → M08
       → M21 → M22 → M23 → M24 → M10 → M16 → M17 → M19 → M20
       → M11 → M18 → M12
```

条件渲染：`M07` 仅当 `years` ≥ 2 条时出现；
`M15` 需 `levels` 非空；`M16 / M20` 需 `matrix.convergence` 非空；
`M17` 需 `gaps` 非空；`M19` 需 `numbers.auc_overall` 存在；
`M21–M24` 各需对应字段存在至少一个非 core 桶（全部为核心词回声时整页跳过）。
因此实际页数以 `deck_content.py` 打印的 `outline pages` 为准，
`deck_outline.md` 由渲染器的页序列反推生成，二者不会脱节。

**裁剪规则**：页数紧张时，先按 `M24 → M21 → M22 → M23` 的顺序裁分析页
（保留与主题最相关的维度即可），再按 `M10 → M02 → M03` 的顺序删。
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
- **固定 6 项**：`01 检索策略` `02 文献体量` `03 主题分布` `04 临床问题` `05 数据与路线` `06 证据综合`。

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

### M21 · Question Map（临床问题图谱）

- **底**：`--paper`。
- **结构**：左 `11fr` 临床问题分桶横向条形（按 `count` 降序，最多 9 桶）+
  右 `5fr` 解读栏（与 M06 同构）。
- **数据**：`questions`（标题与摘要正则命中，可多重归类，`scope=core` 桶不进图）。
- **解读栏（全部由桶数据现算）**：主导临床问题、外部验证覆盖最高的问题方向、
  核心词桶提示。
- **注脚**：`notes.analysis_bucketing`。
- **禁止**：把宽泛桶（如「预后与生存」在预后主题检索中必然命中）当作发现宣称——
  覆盖 ≥80% 的桶已按 core 规则降级为脚注。

### M22 · Modality Mix（数据模态）

- **结构**：与 M21 同构；数据槽位 `modalities`。
- **默认桶**：CT / MRI / 超声 / PET-SPECT / 内镜 / 病理与组织学 / 多模态多参数。
- **解读栏**：主导模态、多模态研究规模（≥10% 记「已成规模」）、核心词桶提示。
- **注脚**：`notes.analysis_bucketing`。
- **禁止**：把「病理 / 组织学」桶读成影像设备——它统计的是**数据来源**
  （含作为参照标准的病理确认），桶名不得改为「病理影像」。

### M23 · Pipeline Mix（技术路线）

- **结构**：与 M21 同构；数据槽位 `pipelines`。
- **默认桶**：影像组学（手工特征）/ 深度学习端到端 / 机器学习模型 /
  混合与临床融合 / 迁移学习与基础模型。
- **解读栏**：主导路线、深度学习与组学两条路线的规模关系（相差 ≤20% 记「并存」）、
  迁移学习 / 基础模型渗透率。
- **注脚**：`notes.analysis_bucketing`。

### M24 · Eval Methods（评价方法）

- **结构**：与 M21 同构；数据槽位 `eval_methods`。
- **默认桶**：AUC / C-index、HR / 生存分析、敏感度 / 特异度、校准、
  决策曲线（DCA）、DeLong 检验、交叉验证、Bootstrap 重抽样。
- **解读栏**：报告率最高的指标；校准 / DCA / DeLong 中报告率 < 20% 的项
  归纳为「方法学缺口」；核心词桶提示。
- **注脚**：`notes.analysis_bucketing`，另须保留「报告率 ≠ 使用质量」口径：
  命中只说明**摘要中报告了**该方法，不评价其使用质量。

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
| 口径必须落字 | `notes` 四条注脚在 M04 / M06 / M08 / M11 中至少各出现一次；M21–M24 每页必须带 `notes.analysis_bucketing` |
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

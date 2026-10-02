# pubmed-retrieve

基于 AI 编程助手（Claude Code / WorkBuddy 等）的 PubMed 生物医学文献检索技能。用自然语言描述研究需求，自动生成 PubMed 检索式，通过 NCBI E-utilities API 执行检索，输出结构化汇总表。

## 功能特性

- **自然语言 → PubMed 检索式**：描述研究主题，自动生成带布尔逻辑、字段限定、MeSH 主题词和文献类型过滤的专业检索式
- **全自动检索管道**：搜索 PMID → 获取详情 → 保存 CSV → 打印汇总表，一条命令完成
- **结构化输出**：CSV 包含 PMID、标题、作者、期刊、日期、DOI、摘要
- **统计汇总**：终端直接输出期刊分布、年份分布和文献列表
- **期刊发表级系统综述**：从检索结果自动编制 PRISMA 2020 系统综述——证据底座（筛选计数、证据分级、定量信号、收敛汇总、研究空白）→ 综述骨架（确定性章节与全部表格由脚本产出，叙述部分留带必引文献清单的写作块）→ Vancouver 参考文献自动编号 → 期刊门槛质检器把关。**纳入标准与 PICOS 按主题定制**，非目标主题误用内置判据会被守卫拦截而非静默误排除
- **学术汇报 deck（消费综述）**：把**系统综述**渲染成医学深蓝瑞士风 PPT（单文件 HTML + 可编辑 .pptx），内置版式校验器。**执行顺序固定为「先综述、后 deck」**：M13–M20 综述页全部由 `review_evidence.json` 派生并写入 `deck_outline.md`，保证 PPT 素材与综述同源；校验器的 F14/F15 会拦截综述层残缺或 PICOS 退回占位的情形

## 安装

### 环境要求

**Python 3.8+** + `requests` + `pandas`。

> 在 WorkBuddy 中运行时无需手动配置：技能会自动使用隔离的托管虚拟环境
> （`~/.workbuddy/binaries/python/envs/default`）并在缺失时安装依赖，不会污染系统环境。

#### 方式一：Miniconda（推荐）

1. 安装 [Miniconda](https://docs.anaconda.com/miniconda/)
2. 打开终端，Conda 安装依赖：

```bash
pip install requests pandas
```

#### 方式二：系统 Python

确保已安装 [Python 3.8+](https://www.python.org/downloads/)，然后：

```bash
python -m pip install requests pandas
```

#### 验证环境

```bash
python --version          # 应输出 3.8+
python -c "import requests, pandas; print('OK')"  # 应输出 OK
```

### 安装为 Skill

```bash
# Claude Code
git clone https://github.com/cloudinfer/pubmed-retrieve.git \
  ~/.claude/skills/pubmed-retrieve/

# WorkBuddy
git clone https://github.com/cloudinfer/pubmed-retrieve.git \
  ~/.workbuddy/skills/pubmed-retrieve/
```

或将 `pubmed-retrieve/` 文件夹手动复制到对应的 skills 目录。

### 验证

在 AI 助手中输入 `/pubmed-retrieve`，应出现在斜杠命令列表中。

## 使用方式

```
/pubmed-retrieve <自然语言描述的研究需求>
```

Skill 会自动完成：
1. 如果未指定时间范围，先与你确认
2. 生成 PubMed 检索式并请你确认
3. 执行检索并展示汇总表
4. 保存完整结果到 CSV 文件

### 示例

**输入**：`/pubmed-retrieve 搜索近五年关于二甲双胍治疗糖尿病的临床试验`

**自动生成的检索式**：
```pubmed
diabetes AND metformin AND "clinical trial"[pt]
```

**输出**：
```
Search (edat) found 187 results, retrieving top X...

[Journal Distribution (Top 10)]:
    2  Diabetes, obesity & metabolism
    1  Cureus
    ...

[Year Distribution]:
    2024: 2
    2025: 3

[Articles]:
  #    PMID       Year   Journal                   Title (truncated)
  1    39737272   2024   Cureus                    Clinical Profile, Comorbidities and Therapies...
  2    39727162   2025   Diabetes, obesity & meta   Impact of the timing of metformin...
  ...
```

CSV 文件保存至 `pubmed_results.csv`，包含 PMID、标题、作者、期刊、DOI、摘要等完整字段。

## 使用示例

### 示例 1：检索临床试验

**输入**：`/pubmed-retrieve 搜索2023-2025年SGLT2抑制剂治疗心力衰竭的临床试验`

**自动生成检索式**：
```pubmed
(SGLT2 inhibitor OR SGLT-2 inhibitor OR "sodium-glucose cotransporter 2 inhibitor") AND ("heart failure" OR HF) AND "clinical trial"[pt]
```

**输出**：
```
Search (edat) found 209 results, retrieving top X...

[Journal Distribution (Top 10)]:
    2  Diabetes, obesity & metabolism
    1  Cardiovascular diabetology
    1  Scientific reports
    ...

[Year Distribution]:
    2023: 68
    2024: 72
    2025: 69

[Articles]:
  #    PMID       Year   Journal                   Title (truncated)
  1    41462250   2025   Cardiovascular diabetolo  Sirtuins and regulatory miRNAs as epigenetic...
  2    41311237   2025   Diabetes, obesity & meta   SGLT2 inhibitor or metformin as standard...
  ...
```

### 示例 2：未指定时间范围

**输入**：`/pubmed-retrieve 找CAR-T细胞治疗实体瘤的文献`

**流程**：Skill 检测到缺少时间范围 → 弹出选择框 → 用户选择"近5年" → 生成检索式并确认 → 执行

**自动生成检索式**：
```pubmed
(CAR-T OR "chimeric antigen receptor" OR "CAR T-cell") AND ("solid tumor" OR "solid cancer")
```

**输出**：906 篇命中，CSV 包含 PMID、标题、期刊、DOI 等 9 个字段。

### 示例 3：自定义结果数量

**输入**：`/pubmed-retrieve 找10篇关于阿尔茨海默病淀粉样蛋白假说的最新文献`

**自动生成检索式**：
```pubmed
(Alzheimer* OR AD) AND ("amyloid hypothesis" OR "amyloid beta" OR "amyloid-beta")
```

**参数**：`--max-results 10`（覆盖默认值 2000）

**输出**：
```
Search (edat) found 6699 results, retrieving top 10...

[Journal Distribution (Top 10)]:
    2  Journal of molecular neuroscience
    1  Chinese medical journal
    1  Acta neuropathologica
    1  Molecular psychiatry
    ...

[Year Distribution]:
    2026: 10
```

## 输出字段

| 字段 | 说明 |
|-------|------|
| Pmid | PubMed ID |
| ISSN | 期刊 ISSN |
| ISSN_Type | print（印刷版）/ electronic（电子版） |
| Title | 文章标题 |
| Authors | 作者列表 |
| Journal | 期刊名称 |
| Date | 出版日期 (YYYY/MM/DD) |
| Doi | DOI 链接 |
| Abstract | 完整摘要 |

## 系统综述（Phase 5，先于 deck）

在检索结果之上编制 PRISMA 2020 系统综述。**纳入标准必须按本次主题定制**——
脚本内置的默认判据是肝细胞癌专用的，用在其他主题上不会报错，
只会静默排除几乎全部记录（实测：395 条中误排除 374 条）。

因此 `--criteria-file` 与 `--picos-file` 是必填项；非肝脏主题未提供时会**直接中止**
并写出可编辑的模板。字段定义、写法规范与完整示例见 **`references/review-criteria.md`**。

```bash
# 1) 证据底座（PRISMA 计数、证据分级、定量信号、收敛汇总、研究空白、meta.picos）
python scripts/review_evidence.py --csv output/pubmed_results.csv --out-dir output \
    --topic "<检索主题>" --query-file query.txt \
    --criteria-file output/criteria.json --picos-file output/picos.json \
    --themes-file output/themes.json \
    --start 2021/01/01 --end 2026/10/02

# 2) 综述骨架（确定性章节与全部表格由脚本产出，叙述留写作块）
python scripts/review_compose.py --evidence output/review_evidence.json \
    --csv output/pubmed_results.csv --out-dir output \
    --topic "<检索主题>" --picos-file output/picos.json

# 3) 填写作块后过质检（P0 必须为 0）
python scripts/review_check.py output/review_draft.md \
    --evidence output/review_evidence.json --refmap output/review_refmap.json --strict
```

质检器覆盖：章节与 31 个小节完整性、引用编号越界、连续 300 字无引用、
正文数字与证据底座一致性、绝对化表述、**表号连续性与交叉引用语义**（R14/R20）、
残留占位符、正文字数下限。

`--picos-file` 的内容会写入 `review_evidence.json` 的 `meta.picos`，
下一阶段的 deck 直接读它渲染 PICOS 页——不必也不应再维护第二份副本。

## 学术汇报 deck（Phase 6，消费系统综述）

**顺序契约：先系统综述，后 deck。** deck 的综述层（M13–M20）全部派生自
`review_evidence.json`，而交给 PPT 环节的唯一素材 `deck_outline.md` 在 deck 阶段写出。
先出 deck 再补综述，PPT 素材里必然缺整层综述，PICOS 页还会退回渲染器里写死的人群描述
（实测：一篇影像组学 deck 的 PICOS 页显示「肝细胞癌患者」）。

- **单文件 HTML deck**：无外部依赖，浏览器直接打开，`← / →` 翻页、`G` 页格索引、`Ctrl+P` 导出 PDF。
- **可编辑 .pptx**：以 `deck_outline.md`（已含综述层）为素材，交由平台 PPT 能力生成。

视觉方向固定为「医学专业 + 科研科技」：瑞士国际主义网格、直角色块、1px 发丝线、
无阴影无渐变，主色医学深蓝 `#0A3D7C`。版式为 M01–M20，其中 M13–M20 是综述层页面，
按叙事位置插入描述层；配色/字号/网格规范见 `references/deck-theme.md`，
版式契约见 `references/deck-layouts.md`。

一键串联（检索 → 综述 → deck）：

```bash
python scripts/pubmed_cli.py -f query.txt -s 2021/01/01 -e 2026/10/02 \
    -o output/pubmed_results.csv \
    --criteria-file output/criteria.json --picos-file output/picos.json \
    --review-themes-file output/themes.json \
    --full --deck-topic "影像组学文献调研"
```

分步执行：

```bash
python scripts/deck_content.py --csv output/pubmed_results.csv --out-dir output \
    --topic "影像组学文献调研" --query-file query.txt \
    --review output/review_evidence.json \
    --start 2021/01/01 --end 2026/10/02
python scripts/deck_build.py    --content output/deck_content.json --out output/deck.html
python scripts/deck_validate.py output/deck.html --strict   # P0 必须为 0
```

`--review` 把证据底座写入 `deck_content.json` 的 `review` 块，
`deck_outline.md` 因此带有 8 页标注「【综述层】」的大纲；不传时 outline 会显式
标注「综述层：缺失」。校验器的 **F14**（综述层残缺）与 **F15**（PICOS 为占位）
专门拦截「deck 与综述脱节」这类问题。

## PubMed 检索语法参考

| 语法 | 示例 |
|------|------|
| 布尔逻辑 AND/OR/NOT | `diabetes AND exercise NOT pediatric` |
| 字段限定 | `"machine learning"[Title/Abstract]` |
| MeSH 主题词 | `diabetes mellitus[MeSH]` |
| 文献类型 | `clinical trial[pt]` / `review[pt]` |
| 精确短语 | `"physical activity"` |
| 通配符 | `Alzheimer*`（匹配 Alzheimer、Alzheimer's） |

## 速率限制

PubMed E-utilities API 限制约 3 次/秒。脚本内置每次请求 0.4 秒延迟。

## 许可证

[Apache License 2.0](./LICENSE)

## 联系与交流

如有问题或建议，欢迎提 Issue 或扫码加微信交流。

![联系方式](./wechat.jpg)

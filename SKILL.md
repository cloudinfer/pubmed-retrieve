---
name: pubmed-retrieve
description: Use whenever the user wants to search for or retrieve literature in biomedicine and clinical medicine — including but not limited to: clinical trials, systematic reviews, meta-analyses, evidence-based medicine, drug and treatment research, surgery, internal medicine, cardiology, oncology, neurology, psychiatry, pediatrics, obstetrics & gynecology, emergency medicine, radiology, pathology, nursing, public health, epidemiology, genetics, immunology, microbiology, pharmacology, physiology, anatomy, or any other life-sciences discipline. Generates a PubMed query, executes the search, and produces a summary table.
---

# PubMed Retrieve Skill

根据用户需求生成 PubMed 检索式，调用 `scripts/` 下的脚本执行检索，并生成文献汇总表。

## 工作流程

### Phase 0: Python 环境检测

**在开始任何检索操作之前，必须先检测 Python 环境。**

脚本依赖 Python 3.8+ 以及 `requests` 和 `pandas`。

#### 检测步骤（按优先级）

**1. 检测 conda / miniconda**（Windows 上最常见）：

```powershell
# 检查常见安装路径
Test-Path "$env:USERPROFILE\miniconda3\shell\condabin\conda-hook.ps1"
# 或
Get-Command conda -ErrorAction SilentlyContinue
```

**2. 验证 Python 可用**：

```bash
python --version
```

**3. 都不行 → 询问用户**：用 `AskUserQuestion` 告知未检测到 Python 环境，提供安装选项：
- "安装 Miniconda (推荐)" — https://docs.anaconda.com/miniconda/
- "安装 Python" — https://www.python.org/downloads/
- "取消"

**4. 环境就绪后安装依赖**：

```bash
pip install requests pandas
# 如果 pip 不可用：
python -m pip install requests pandas
```

### Phase 1: 理解需求 → 生成检索式

从用户输入中提取以下信息，遵循确认规则：

| 要素 | 说明 | 处理规则 |
|------|------|----------|
| 核心主题 | 研究关键词 / 研究问题 | 必填，不明确时主动确认 |
| 时间范围 | 起止日期 (YYYY/MM/DD) | **用户未指定时必须确认**，不提供默认值 |
| 文献类型 | clinical trial / review / RCT / meta-analysis 等 | 不限 (可选) |
| 字段限定 | Title/Abstract / MeSH / Author / Journal | 不限 (可选) |
| 最大结果数 | 预期返回文献数 | **默认 2000** |

**时间范围确认规则**：如果用户没有明确给出时间范围（如"近五年"、"2020-2024"），
必须在执行检索前用 `AskUserQuestion` 确认大致范围，
选项至少包括："近1年"、"近5年"、"近10年"、"不限时间范围"。

#### 检索式生成规则

1. **布尔逻辑**: 用 `AND` / `OR` / `NOT` (必须大写) 组合关键词，括号控制优先级
2. **字段限定**: `text[Title/Abstract]`、`concept[MeSH]`、`author[Author]`、`journal[Journal]`
3. **文献类型**: `clinical trial[pt]`、`review[pt]`、`"systematic review"[pt]`、`"randomized controlled trial"[pt]`
4. **通配符**: `*` 进行词根扩展 (如 `Alzheimer*` 匹配 Alzheimer、Alzheimer's)
5. **精确短语**: 双引号包裹 (如 `"machine learning"`)

#### 检索式示例

```
# 简单关键词
diabetes AND exercise AND "physical activity"

# 字段限定
("deep learning"[Title/Abstract] OR "neural network"[Title/Abstract]) AND "medical imaging"[MeSH]

# 文献类型
(Alzheimer* OR dementia) AND ("early diagnosis" OR "early detection") AND "systematic review"[pt]

# 复杂组合
(cancer OR neoplasm) AND immunotherapy[Title/Abstract] AND "clinical trial"[pt] NOT pediatric
```

生成检索式后，向用户展示完整的检索计划（检索式 + 时间范围 + 最大结果数），等待确认后再执行检索。

如果用户未提供时间范围，必须先确认再生成检索式。

### Phase 2: 执行检索

**重要**：检索式包含括号、引号、方括号等特殊字符，直接通过 shell 传参会被错误拆分。
**必须使用 `--query-file` 方式**：先将检索式写入临时文件，再从文件读取。

#### 执行步骤

**Step 1**: 将检索式写入临时文件：

```bash
# 用 Write 工具写入 .claude/tmp_query.txt，内容为检索式
```

**Step 2**: 执行检索（根据 Phase 0 检测的环境选择命令）：

**Windows（conda）**：
```powershell
& "$env:USERPROFILE\miniconda3\shell\condabin\conda-hook.ps1" ; conda activate "$env:USERPROFILE\miniconda3" ; python .claude/skills/pubmed-retrieve/scripts/pubmed_cli.py -f .claude/tmp_query.txt -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 -o pubmed_results.csv
```

**macOS / Linux（conda）**：
```bash
source "$HOME/miniconda3/bin/activate" && python .claude/skills/pubmed-retrieve/scripts/pubmed_cli.py -f .claude/tmp_query.txt -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 -o pubmed_results.csv
```

**无 conda（系统 Python）**：
```bash
python .claude/skills/pubmed-retrieve/scripts/pubmed_cli.py -f .claude/tmp_query.txt -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 -o pubmed_results.csv
```

#### 参数说明

| 参数 | 说明 |
|------|------|
| `--query-file` / `-f` | 从文件读取检索式（**推荐**，避免 shell 转义问题） |
| `--query` / `-q` | 直接传检索式（仅简单关键词可用） |
| `--start-date` / `-s` | 起始日期，格式 YYYY/MM/DD |
| `--end-date` / `-e` | 结束日期，默认今天 |
| `--max-results` / `-m` | 最大结果数，默认 2000 |
| `--output` / `-o` | 输出 CSV 文件名 |

CLI 自动完成四步：搜索 PMID → 获取详情 → 保存 CSV → 打印汇总表。

### Phase 3: 解读结果

CLI 输出包含：

1. **检索概览**: 检索式、时间范围、检索日期、命中数
2. **期刊分布**: 发文最多的 10 个期刊
3. **年份分布**: 各年份文献数量
4. **文献列表**: PMID、年份、期刊、标题

同时生成 CSV 文件，包含全部字段：`Pmid, ISSN, ISSN_Type, Title, Authors, Journal, Date, Doi, Abstract`

如用户需要进一步分析（筛选、统计、下载全文链接等），基于 CSV 或返回的结果数据继续处理。

## 依赖

```bash
pip install requests pandas
```

## 注意事项

1. **检索式确认**: 执行前必须向用户展示检索式并确认
2. **API 速率**: 脚本内置 0.4s 延迟，批量检索时注意耗时
3. **结果上限**: PubMed E-utilities 单次最多返回约 10,000 条
4. **日期格式**: 严格使用 `YYYY/MM/DD`

## 常见问题

| 问题 | 处理方式 |
|------|----------|
| 结果为空 | 检查检索式语法；放宽条件；扩大时间范围 |
| 结果太多 | 添加限定词；缩小时间；限定文献类型 |
| 需要更精确 | 使用 MeSH 主题词 `term[MeSH Major Topic]` |
| 下载全文 | PubMed 仅提供元数据；通过 DOI 链接跳转出版商 |

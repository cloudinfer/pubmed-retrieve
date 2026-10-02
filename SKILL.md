---
name: pubmed-retrieve
description: Use whenever the user wants to search for or retrieve literature in biomedicine and clinical medicine — including but not limited to clinical trials, systematic reviews, meta-analyses, evidence-based medicine, drug and treatment research, surgery, internal medicine, cardiology, oncology, neurology, psychiatry, pediatrics, obstetrics & gynecology, emergency medicine, radiology, pathology, nursing, public health, epidemiology, genetics, immunology, microbiology, pharmacology, physiology, anatomy, or any other life-sciences discipline. Generates a PubMed query, executes the search, produces a summary table and analysis report, then automatically composes a journal-grade systematic review draft in a medical deep-blue Swiss grid style, and only afterwards renders the academic report deck (single-file HTML slides plus an editable PPTX) out of that review — no further user request needed for Phase 5 and Phase 6.
---

# PubMed Retrieve Skill

根据用户需求生成 PubMed 检索式，调用 `scripts/` 下的脚本执行检索，生成文献汇总表；
随后**自动**编制期刊发表级系统综述草稿，**再自动**把综述（而非仅检索统计）渲染成学术汇报 deck
（单文件 HTML + 可编辑 PPTX）——Phase 5 / Phase 6 无需用户再次要求，检索完成即按序串联执行。

> **执行契约**：Phase 1–4 完成后，Agent 必须不经询问直接继续 Phase 5（系统综述）与
> Phase 6（deck）。**顺序不可颠倒**，理由见下节。
> 仅当用户在本次请求中**明确表示不要**综述 / deck 时才跳过对应阶段，并向用户说明已跳过。

## 阶段顺序（先综述、后 deck，不可颠倒）

```
Phase 1–4   检索与解读           → pubmed_results.csv + 分析报告
Phase 5     系统综述             → review_evidence.json + review_draft.md + .docx
Phase 6     deck                 → deck_content.json(含综述层) + HTML deck + .pptx
```

这不是风格偏好，而是**数据依赖**：

- deck 的综述层（M13 PICOS、M14 PRISMA、M15 证据等级、M16 收敛、M17 空白与议程、
  M18 结论、M19 定量性能、M20 核心发现）**全部由 `review_evidence.json` 派生**。
  其中 M13 的人群描述直接取自证据底座的 `meta.picos`。
- `deck_outline.md`——**交给 PPT 环节的唯一素材**——在 deck 阶段写出。
  因此「先出 deck、再补综述页」必然导致 PPT 素材缺整层综述；
  更糟的是 M13 会退回渲染器里的硬编码人群（真实案例：一篇影像组学 deck 的 PICOS 页
  显示「肝细胞癌患者，不限分期与治疗方式」，与本主题无关，也与同批综述正文相互矛盾）。
- 反向只需一次：综述做完再跑 deck，`deck_content.json` / `deck_outline.md` / HTML / `.pptx`
  同时获得综述层，且四者同源。

**唯一允许的例外**：用户明确只要 deck（不要综述）。此时 deck 退化为纯描述性版本，
`deck_outline.md` 会显式标注「综述层：缺失」，`deck_validate.py` 不做综述层完备性检查
（若强行混入部分综述页，F14 会阻断）。

## 路径约定

本 skill 的脚本位于 **本 SKILL.md 所在目录**下的 `scripts/`。请以 skill 目录为基准定位脚本，不要硬编码 `.claude/skills/...` 这类路径。

| 子目录 | 内容 |
|--------|------|
| `scripts/` | `pubmed_cli.py`（检索 CLI）、`pubmed_script.py`（E-utilities 实现）、`review_evidence.py` / `review_compose.py` / `review_check.py`（Phase 5 综述链路）、`deck_content.py` / `deck_build.py` / `deck_validate.py`（Phase 6 deck 链路） |
| `assets/deck/` | `template-medical.html`（医学深蓝瑞士风单文件 deck 模板） |
| `references/` | `deck-theme.md`（配色/字号/网格规范）、`deck-layouts.md`（M01–M20 版式契约）、`review-standard.md`（期刊门槛与语言禁忌）、`review-criteria.md`（**纳入标准/PICOS 定制指南，Phase 5 必读**） |

常见安装位置：

| 环境 | skill 根目录 |
|------|--------------|
| WorkBuddy | `~/.workbuddy/skills/pubmed-retrieve/` |
| Claude Code | `~/.claude/skills/pubmed-retrieve/` |
| 项目级 | `<workspace>/.workbuddy/skills/pubmed-retrieve/` |

下文记作 `{SKILL_DIR}`。**首次使用前请先用 Glob/Read 确认脚本真实位置**（例如 `Glob **/pubmed-retrieve/scripts/pubmed_cli.py`），再拼接绝对路径执行。

## 工作流程

### Phase 0: Python 环境检测

**在开始任何检索操作之前，必须先检测 Python 环境。**

脚本依赖 Python 3.8+ 以及 `requests` 和 `pandas`。

#### 检测步骤（按优先级）

**1. WorkBuddy 托管 Python 虚拟环境（若在 WorkBuddy 中运行，首选）**

WorkBuddy 会把依赖装在隔离的托管 venv 里，不污染用户系统环境。先检查是否已就绪：

```bash
# Windows
PY="$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
# macOS / Linux：PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"

[ -x "$PY" ] && "$PY" -c "import requests, pandas; print('deps ok')"
```

若输出 `deps ok`，直接使用该解释器，**无需再安装任何依赖**，跳到 Phase 1。

若 venv 不存在，先用托管解释器创建，再装依赖（用后台任务执行，避免前台超时中断）：

```bash
# 托管解释器版本号以本机实际安装为准，例如：
#   ~/.workbuddy/binaries/python/versions/3.13.12/python.exe
"$HOME/.workbuddy/binaries/python/versions/<version>/python.exe" \
  -m venv "$HOME/.workbuddy/binaries/python/envs/default"

"$HOME/.workbuddy/binaries/python/envs/default/Scripts/pip.exe" install requests pandas
```

> 依赖安装耗时约 20–40s，**建议用后台任务执行**（`run_in_background=true`）。
> 若不确定托管解释器的具体版本目录，用 Glob 搜索 `binaries/python/versions/*/python.exe` 确认。

**2. 检测 conda / miniconda**（Windows 上常见）：

```powershell
Test-Path "$env:USERPROFILE\miniconda3\shell\condabin\conda-hook.ps1"
Get-Command conda -ErrorAction SilentlyContinue
```

**3. 系统 Python**：

```bash
python --version
python -c "import requests, pandas; print('deps ok')"
```

**4. 都不行 → 询问用户**：用 `AskUserQuestion` 告知未检测到 Python 环境，提供安装选项：
- "安装 Miniconda (推荐)" — https://docs.anaconda.com/miniconda/
- "安装 Python" — https://www.python.org/downloads/
- "取消"

**5. 通用依赖安装**（仅在 1–3 均不可用时）：

```bash
pip install requests pandas
# 如果 pip 不可用：
python -m pip install requests pandas
```

> 排查提示：系统 Python 报 `ModuleNotFoundError: No module named 'requests'` 属常见情况，
> 优先切到 WorkBuddy 托管 venv（步骤 1），无需改动用户系统环境。

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

用户已给出明确范围（如"近一个月""2020-2024"）时**不要再追问时间范围**，
但仍需展示完整检索计划并确认后执行（见下）。

#### 检索式生成规则

1. **布尔逻辑**: 用 `AND` / `OR` / `NOT` (必须大写) 组合关键词，括号控制优先级
2. **字段限定**: `text[Title/Abstract]`、`concept[MeSH]`、`author[Author]`、`journal[Journal]`
3. **文献类型**: `clinical trial[pt]`、`review[pt]`、`"systematic review"[pt]`、`"randomized controlled trial"[pt]`
4. **通配符**: `*` 进行词根扩展 (如 `Alzheimer*` 匹配 Alzheimer、Alzheimer's)
5. **精确短语**: 双引号包裹 (如 `"machine learning"`)

#### ⚠️ 布尔优先级陷阱（高频出错点）

PubMed **不保证** `AND` 先于 `OR` 求值。**混用 `AND`/`OR` 时必须显式加括号**，否则语义会跑偏：

```
# ❌ 错误：意图是 (A 或 B 或 C) 且 D，实际可能被解析为 A OR B OR (C AND D)，结果虚高
A OR B OR C AND D

# ✅ 正确
(A OR B OR C) AND D
```

另外：**先想清楚"同义词组"与"限定条件"的边界**。
`("radiomics"[Title/Abstract] OR "radiomic"[Title/Abstract] ...)` 这类**纯同义词扩展通常不需要再 AND 领域词**——
主题词本身已隐含领域（如 radiomics 必属医学影像），再加 `AND "medical imaging"` 会大量漏检。
**宁可先跑一轮看数量级，再决定是否收紧**，不要一上手就叠限定。

#### 检索式示例

```
# 简单关键词
diabetes AND exercise AND "physical activity"

# 字段限定
("deep learning"[Title/Abstract] OR "neural network"[Title/Abstract]) AND "medical imaging"[MeSH]

# 文献类型
(Alzheimer* OR dementia) AND ("early diagnosis" OR "early detection") AND "systematic review"[pt]

# 同义词扩展 + MeSH（推荐写法：同义词全括在一起）
("radiomics"[Title/Abstract] OR "radiomic"[Title/Abstract] OR "radiogenomics"[Title/Abstract] OR "radiomics"[MeSH Terms])

# 复杂组合
(cancer OR neoplasm) AND immunotherapy[Title/Abstract] AND "clinical trial"[pt] NOT pediatric
```

生成检索式后，向用户展示完整的检索计划（**检索式 + 时间范围 + 最大结果数**），
用 `AskUserQuestion` 确认后再执行检索。

### Phase 2: 执行检索

**重要**：检索式包含括号、引号、方括号等特殊字符，直接通过 shell 传参会被错误拆分。
**必须使用 `--query-file` 方式**：先将检索式写入临时文件，再从文件读取。

#### 执行步骤

**Step 1**: 用 Write 工具将检索式写入**当前 workspace** 的临时文件，例如
`<workspace>/.workbuddy/tmp_query.txt`（内容为单行检索式，不要加换行或注释）。**不要**写到 `.claude/` 下。

**Step 2**: 执行检索（根据 Phase 0 检测的环境选择命令，路径全部用绝对路径）：

**WorkBuddy 托管 venv（首选）**：
```bash
cd "<workspace>" && \
"$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe" \
  "<SKILL_DIR>/scripts/pubmed_cli.py" \
  -f "<workspace>/.workbuddy/tmp_query.txt" \
  -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 \
  -o "<workspace>/pubmed_results.csv"
```

**Windows（conda）**：
```powershell
& "$env:USERPROFILE\miniconda3\shell\condabin\conda-hook.ps1" ; conda activate "$env:USERPROFILE\miniconda3" ; python "<SKILL_DIR>/scripts/pubmed_cli.py" -f "<workspace>/.workbuddy/tmp_query.txt" -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 -o "<workspace>/pubmed_results.csv"
```

**macOS / Linux（conda）**：
```bash
source "$HOME/miniconda3/bin/activate" && python "<SKILL_DIR>/scripts/pubmed_cli.py" -f "<workspace>/.workbuddy/tmp_query.txt" -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 -o "<workspace>/pubmed_results.csv"
```

**无 conda（系统 Python）**：
```bash
python "<SKILL_DIR>/scripts/pubmed_cli.py" -f "<workspace>/.workbuddy/tmp_query.txt" -s "YYYY/MM/DD" -e "YYYY/MM/DD" -m 2000 -o "<workspace>/pubmed_results.csv"
```

**Step 3**: 完成后删除临时检索式文件。

> **执行提示**：几百条文献的详情抓取约需 20–60s（每 50 条一批，批间 0.4s 延迟），
> 建议用后台任务运行并设定足够超时。若用 `| tail -N` 截断输出，**注意 tail 会吃掉开头的
> 「检索概览 / 期刊分布 / 年份分布」段**——需要这些统计时请勿截断，或直接改为读取 CSV 自行统计。

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

#### ⚠️ 日期字段语义：EDAT 而非 PDAT

脚本使用 `datetype=edat`，即按**文献进入 PubMed 的入库日期**筛选，**不是期刊出版日期**。
这直接影响"近一个月""近一年"这类需求的口径：

- EDAT 命中数**远多于**同期正式出版量（含在线优先出版、预印后收录等）。
- 一条记录可能标注 `Date` 为 2026 年，但 EDAT 落入检索窗口。
- **必须在最终答复中明确说明口径**，并提示"与期刊正式出版月不完全一致"，避免用户误解。

若用户明确要求按出版日期筛选，需改用 `datetype=pdat`（当前脚本未暴露该参数，需修改脚本或改用 E-utilities 直查）。

### Phase 3: 解读结果

CLI 输出包含：

1. **检索概览**: 检索式、时间范围、检索日期、命中数
2. **期刊分布**: 发文最多的 10 个期刊
3. **年份分布**: 各年份文献数量
4. **文献列表**: PMID、年份、期刊、标题

同时生成 CSV 文件，包含全部字段：`Pmid, ISSN, ISSN_Type, Title, Authors, Journal, Date, Doi, Abstract`

#### 3.1 基于 CSV 做主题/模态聚类（推荐增值步骤）

命中量较大时（>100 篇），用关键词分桶给出分布表能显著提升可读性。
**用 pandas 读 CSV，不要用 shell 文本工具**：

```python
import pandas as pd
df = pd.read_csv("pubmed_results.csv")
txt = (df["Title"].fillna("") + " " + df["Abstract"].fillna("")).str.lower()

groups = {
    "CT":          r"\bct\b|computed tomograph|cone-beam|cbct|dual-energy",
    "MRI":         r"\bmri\b|magnetic resonance|multiparametric|\bdwi\b|\badc\b|t1 mapping",
    "超声":         r"\bultrasound\b|ultrasonograph|elastograph|\bdoppler\b",
    "深度学习":      r"deep learning|convolutional|\bcnn\b|transformer|neural network|u-net",
    "传统机器学习":   r"machine learning|random forest|xgboost|nomogram|\bsvm\b|lasso",
    "多中心/外部验证": r"multicent|multi-cent|external validation|generalizab|prospective",
}
for n, k in sorted(((txt.str.contains(p, regex=True, na=False).sum(), k) for k, p in groups.items()), reverse=True):
    print(f"{n:4d} ({n/len(df)*100:5.1f}%)  {k}")
```

##### ⚠️ 关键词正则的两个高频踩坑

1. **短词/缩写必须加 `\b` 词边界**：`\bct\b` 而非 `ct`（否则命中 "detect""factor"）。
2. **子串陷阱——务必检查关键词会不会出现在无关常见词里**。真实案例：
   - `spect` 会命中 **re`spect`ive / retro`spect`ive / per`spect`ive / expect**，导致"PET/SPECT"桶虚高数倍。
     正确写法：`\bspect\b`（并用 `\bpet\b` 而非 `pet`）。
   - `\bus\b`（超声）会命中代词 us；`ai`/`ai` 会命中 "main""domain"。
   - `adc` 会命中 "advocacy" 等；建议 `\badc\b`。
   - `oral`（口腔/头颈）会命中 **tem`poral`**（颞叶）、"temporal lobe" —— 真实案例：一次影像组学检索中
     `oral` 使"头颈/口腔"桶从 36 篇虚高到 103 篇（占全量 25%）。正确写法：`\boral\b` 或 `oral squamous`。
   - **经验规律：越短的解剖词越危险。** 三字母级（`us` / `ai` / `pet` / `oral`）几乎必然翻车，必须加 `\b`；
     `prostate` / `renal` / `bladder` 等长词相对安全，但统一加 `\b` 成本极低，建议一律加。
   - **自检方法**：若某桶占比异常高（如 >20%），把该桶拆成子关键词逐项计数，即可快速定位"凶手"词。
3. **`str.contains` 含捕获组会触发 `UserWarning`**：用 `(?:...)` 非捕获组，或忽略该警告。
4. **统计口径要写明**：分桶是**可多重归类**的（一篇文献可同时属于 CT 与深度学习），
   故各桶占比之和 **>100%**；务必在报告中标注，否则会被误读为互斥分类。

#### 3.2 引用文献的 PMID 核对（强制）

**报告中引用的每一条 `PMID → 标题/期刊`，都必须回查 CSV 校验后才能写入。**
凭印象或凭标题相似度外推 PMID **极易张冠李戴**（真实案例：把 `42670019`「CT texture phantom dataset」
误配到 habitat 主题；凭空写出不存在的 PMID）。

```python
df["Pmid"] = df["Pmid"].astype(str)
for p in ["42759982", "42721921", "42670019"]:
    r = df[df["Pmid"] == p]
    print(f"{p}  {r.iloc[0]['Journal']} | {r.iloc[0]['Title']}" if len(r) else f"{p}  *** NOT FOUND ***")
```

出现 `*** NOT FOUND ***` 或标题对不上时，**改用关键词在 CSV 内反查真实 PMID**，
或直接删除该引用——**绝不保留未经校验的 PMID**。

#### 3.3 交付物

默认交付两件：

1. **CSV**：全量元数据（可附 DOI 链接）。
2. **分析报告（Markdown）**：检索式与口径说明 → 期刊分布 → 模态/方法/疾病分布 → 前沿方向与代表文献（PMID 已校验）→ 趋势判断与局限。

### Phase 4: 提交（中间节点，非终点）

用 `present_files` 展示报告与 CSV（若 Phase 5/6 产物即将就绪，可与最终交付合并为一次展示）。
在答复中复述：命中量、时间口径（EDAT）、关键分布数字、主要趋势，
并说明"PubMed 仅提供题录与摘要元数据，全文需经 DOI 跳转出版商"。

Phase 4 完成后**不要停下等待用户指示**，直接进入 **Phase 5（系统综述）**，
完成后再进入 Phase 6（deck）。顺序见「阶段顺序」一节。

---

### Phase 5: 编制期刊发表级系统综述（自动执行，先于 deck）

Phase 4 完成后自动进入本阶段。在检索结果之上，编制一份**可投稿级别**的系统综述。
与 Phase 6 的分工：Phase 5 回答「这些证据支持什么、缺什么、证据有多可靠」（系统性综合）；
Phase 6 回答「检索到了什么、结论长什么样」（把本阶段的结论渲染成可汇报的页面）。
**Phase 5 必须有自己的分析主题、证据分级与收敛汇总，不得复用 Phase 6 的描述性主题桶。**

本阶段的产物是 Phase 6 的**输入**，两个文件缺一不可：

| 产物 | 用途 |
|------|------|
| `review_evidence.json` | 计数、分级、收敛、空白、定量信号、`meta.picos` —— Phase 6 综述层的**唯一数据源** |
| `review_draft.md` | 综述正文（叙述性综合），也是最终 `.docx` 的源 |

凡声明「要可发表」「要期刊水平」「要投稿」，一律按 `references/review-standard.md`
执行；未达门槛不得交付。

#### 5.1 定制纳入标准 → 构建证据底座

> **Step 0（必做，不可跳过）：先按本次主题改写纳入标准与 PICOS。**
>
> `review_evidence.py` 与 `review_compose.py` 内置的纳入标准是**上一轮肝脏主题任务留下的
> 肝细胞癌专用规则**（`POP_IN` / `OTHER_PRIMARY` / PICOS 措辞）。把它用在其他主题上
> **不会报错**——它只会静默排除几乎全部记录。真实案例：一次「影像组学」检索命中 395 条，
> 用内置标准后「潜在纳入」只剩 **14 条**（误排除 374 条，占 95%）；综述骨架里还出现了
> 「经病理或临床确诊的肝细胞癌患者」和 EphA2 受体。
>
> 为此两个脚本都加了**守卫**：当主题不含肝脏关键词（`hepat` / `hcc` / `liver` / `hepatic` / 肝）
> 且未提供定制文件时，脚本**直接中止（exit 2）**，并在输出目录生成可编辑的模板：
> `criteria_template.json` / `picos_template.json`。按模板填写后重跑即可。
> 只有主题确属肝脏时才会放行，或用 `--allow-default-criteria` / `--allow-default-picos` 显式放行。
>
> 定制方法、字段含义与完整示例见 **`references/review-criteria.md`**。

```bash
"$PY" "<SKILL_DIR>/scripts/review_evidence.py" \
  --csv "<workspace>/output/pubmed_results.csv" \
  --out-dir "<workspace>/output" \
  --topic "<检索主题>" \
  --query-file "<workspace>/.workbuddy/tmp_query.txt" \
  --criteria-file "<workspace>/output/criteria.json" \
  --picos-file "<workspace>/output/picos.json" \
  --themes-file "<workspace>/output/themes.json" \
  --start "2021/01/01" --end "2026/10/02" --max-results 2000 \
  --search-date "<今天 YYYY-MM-DD>"
```

`--criteria-file` 与 `--picos-file` 在这里**都要给**：前者管**筛选判据**（正则），
后者管**成文措辞**（PICO 表、纳入排除标准表、关键词）。PICOS 会被写入
`meta.picos` / `meta.picos_source`，Phase 6 的 deck 直接读取它渲染 M13 页——
deck 因此**不可能**写出与本综述不同的人群描述。

产出 `review_evidence.json`（PRISMA 计数、证据等级、定量信号、文献矩阵、收敛汇总、
研究空白；另记 `meta.criteria_source` / `meta.picos` 以便复核用了哪套判据）与
`review_corpus.md`（代表文献摘要集）。

**筛选量级自检**：跑完先看 `eligible` 占 `identified` 的比例。
若低于一半，多半是判据过紧或主题词没对齐，**先查判据再往下走**，不要直接交付。
本次正确配置下该比例为 313/395 ≈ 79%。

四条方法学约束（答复中必须声明）：

- **证据分级是暂定的**：由摘要中报告的研究设计自动推断，全文复核后应更新。
- **PRISMA 计数是题录层面的**：「潜在纳入」不等于「已纳入」。
- **PROBAST / GRADE 表留空**：必须基于全文评估，**不得用摘要推断填充**。
- **收敛指标在全量文献池计算**：不在精选语料上算，避免抽样偏倚。

#### 5.2 生成综述骨架（确定性内容全部由脚本产出）

```bash
"$PY" "<SKILL_DIR>/scripts/review_compose.py" \
  --evidence "<workspace>/output/review_evidence.json" \
  --csv "<workspace>/output/pubmed_results.csv" \
  --out-dir "<workspace>/output" --topic "<检索主题>" \
  --picos-file "<workspace>/output/picos.json" [--regno "CRD4202xxxx"]
```

脚本自动写入**全部可从 CSV 确定性派生的内容**：中英题名与摘要的数字部分、
PICOS 表、完整检索式、PRISMA 计数表与流程图、证据等级分布表、
纳入研究特征表、定量信号表、主题收敛汇总表、PROBAST 与 GRADE 表结构、
六项声明、Vancouver 参考文献、PRISMA 2020 核对表附录、检索式附录、
引证样本清单附录、逐条评估表附录。

**结果章表号由 `T_PRISMA`…`T_GAPS` 常量统一派生**（表 1 筛选计数 → 表 8 研究空白），
表题与附录 A 核对表的「报告位置」列共用同一组常量。**不要在任何地方硬编码表号字面量**——
历史上曾因此让核对表把 PROBAST 表标成「表 2」而正文实为「表 3」，
`review_check.py` 的 R20 现在会阻断这类语义错位。

只有**叙述性综合**留作 `WRITE-BLOCK`，每个块带明确任务描述、字数区间与**必引 PMID 清单**。
写作因此是有约束的填空，不是自由发挥。

#### 5.3 撰写叙述部分

逐块填写 `review_draft.md` 中的 `WRITE-BLOCK`，填写后整块删除注释。要求：

- 每个块只用该块必引清单内的文献支撑实证论断（背景性表述可引指南或教科书）；
- 不得引用 corpus 之外的 PMID 来陈述本次检索的发现；
- 严格遵循 `references/review-standard.md` 的语言禁忌（禁绝对化表述、禁 vibe citing）；
- PROBAST / GRADE / 待提取字段一律保持「待评估」「待提取」，不得提前填值。

#### 5.4 期刊门槛质检（P0 必须为 0 才能交付）

```bash
"$PY" "<SKILL_DIR>/scripts/review_check.py" "<workspace>/output/<综述>.md" \
  --evidence "<workspace>/output/review_evidence.json" \
  --refmap "<workspace>/output/review_refmap.json" --strict
```

检查项：章节与 31 个小节完整性、写作块是否清零、引用编号越界、
连续 300 字无引用、正文数字与证据底座一致性、绝对化表述、
图表编号连续性与**交叉引用语义**、残留占位符、正文字数下限（系统综述 12,000 字）。

其中 R14/R20 针对的是排版前最容易漏掉的一类错误，二者都是 P0：

| 规则 | 检查内容 |
|------|----------|
| R14 | 每个结果表都必须有 `**表 N　标题**` 编号表题；编号唯一、从 1 连续无跳号；任何「表 N」引用都能落到真实表题上 |
| R20 | 附录 A 的 PRISMA 核对表「报告位置」列引用的表号，必须落在**语义相符**的表上（第 11/18 条须指向偏倚风险表、第 17 条指向特征表、第 22 条指向确定性表） |

> 这两条是补上的历史缺口：此前只校验「编号连续」，不校验「指对了表」，
> 于是把 PROBAST 标成「表 2」而正文实为「表 3」也能通过。
> 注意核对表在**附录 A**（位于参考文献之后），因此 `review_check.py` 用全文而非
> `split_body()` 之后的正文做这项检查——否则会漏检整张核对表。

#### 5.5 排版为可编辑文档

走 `tencent-docx` 将 Markdown 排版为论文格式 `.docx`（标题层级、中英题名、
结构化摘要、表格、参考文献悬挂缩进）。

**排版阶段的两条硬约束**：

1. **必须保留正文既有的「表 N／图 N」编号，不得按出现顺序重新编号。**
   综述正文的编号由 `review_compose.py` 统一派生（表 1–表 8），是唯一权威来源；
   渲染器一旦按位置重新编号，就会与附录 A 核对表的引用脱节。
   源 Markdown 里表题位于**表格之前**的整行加粗段落（`**表 3　纳入研究基本特征**`），
   生成 HTML/Word 时需**向前看一行**取表题，取不到时保留表题缺失状态而不是自造编号。
2. **不得改动正文内容。** 排版只负责版式；发现内容层问题（如交叉引用错误）
   应回到 5.2/5.3 修源文件，而不是在 HTML/Word 里就地改字。

> **Windows 环境绕行**：`tencent-docx` 的 `scripts/wb/local/setup-html-to-docx.sh`
> 使用 Linux 布局的 `<venv>/bin/python` 判定依赖，在 Windows 上会**静默跳过安装**，
> 随后转换阶段才报缺 `python-docx`。绕行方式是直接用 Windows 布局的解释器装依赖：
>
> ```bash
> uv pip install --python "$HOME/.venv-html-to-docx/Scripts/python.exe" \
>   --only-binary=:all: -r "<tencent-docx>/skills/html-to-docx/scripts/requirements.txt"
> ```

#### 5.6 提交（中间节点，非终点）

用 `present_files` 展示系统综述 `.docx` 与 Markdown 源。
**不要在此时停下**——deck 与 PPT 仍依赖本阶段产物，直接进入 Phase 6，
把 `review_evidence.json` 一并交给下一阶段。

---

### Phase 6: 生成学术汇报 deck（自动执行，含综述层）

Phase 5 完成后自动进入本阶段。把**综述**（而非仅检索统计）转成一份可汇报的学术 deck。
视觉方向固定为 **「医学专业 + 科研科技」**，
采用**瑞士国际主义**方法论（16 列网格、直角色块、1px 发丝线、极致字号对比、
无阴影无渐变无圆角），主色**医学深蓝 `#0A3D7C`**。

设计依据（**生成前必读，不要凭记忆发挥**）：

| 文件 | 内容 |
|------|------|
| `references/deck-theme.md` | 调色板白名单、字体栈、网格与安全边距、字号阶梯、禁止清单 F01–F15 |
| `references/deck-layouts.md` | M01–M20 锁定版式契约、`deck_content.json` 字段定义、内容映射与写作规则 |

**交付两件**：① 单文件 HTML deck（高保真、可翻页演示、可打印为 PDF）；② 可编辑 `.pptx`。

#### 6.1 生成内容模型 `deck_content.json`（必须带 `--review`）

```bash
PY="$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"   # 见 Phase 0

"$PY" "<SKILL_DIR>/scripts/deck_content.py" \
  --csv "<workspace>/output/pubmed_results.csv" \
  --out-dir "<workspace>/output" \
  --topic "<检索主题，≤30 字>" \
  --query-file "<workspace>/.workbuddy/tmp_query.txt" \
  --review "<workspace>/output/review_evidence.json" \
  --start "2021/01/01" --end "2026/10/02" --max-results 2000 \
  --search-date "<今天 YYYY-MM-DD>"
```

产出 `output/deck_content.json`（唯一数据源）与 `output/deck_outline.md`（逐页大纲，
**同时是交给 PPT 环节的唯一素材**）。

**`--review` 是本阶段的必需参数，不是可选项。** 它把 Phase 5 的证据底座
（PRISMA 计数、证据等级、收敛汇总、研究空白、定量信号、`meta.picos`）
以精简形态写入 `deck_content.json` 的 `review` 块，并据此渲染大纲中的
**8 页综述层**。不传时 outline 会显式标注「综述层：缺失」，
此时交付给 PPT 环节的素材就不含任何综述内容——这正是要避免的情况。

deck 的页面构成分三层，综述层按**叙事位置插入**描述层，不追加在末尾：

| 层 | 版式 | 页面 | 数据来源 |
|----|------|------|----------|
| 口径层 | M01 / M03 / M04 | 封面、目录、检索策略 | 检索元数据 |
| **综述层** | **M13 / M14** | **研究问题与 PICOS、PRISMA 筛选流程** | `meta.picos`、`prisma` |
| 描述层 | M05 / M06 / M07 / M08 / M09 / M10 | 体量、期刊、趋势、主题分布、代表文献、方向对照 | 检索统计 |
| **综述层** | **M15** | **证据等级分布** | `levels` |
| **综述层** | **M16 / M17 / M19 / M20** | **收敛汇总、空白与议程、定量性能、核心发现** | `matrix`、`gaps`、`numbers` |
| 收束层 | M11 / M18 / M12 | 趋势与局限、综述结论、结论 | 描述层 + 综述层 |

综述层页面**一律由证据底座派生**，渲染器内不得写死结论：

- M13 的 P/O/I/C/S 五行取自 `review_evidence.json` → `meta.picos`；
  缺失时页面显示占位符，`deck_validate.py` 的 F15 会阻断。
- M17 的「议程建议」由 `gaps` 按 `priority` 排序后取 `implication` 生成。
- M20 的四条「核心发现」由 `convergence` / `levels` / `numbers` / `prisma` 现算。
- M15 / M16 / M18 / M19 同理，全部读 `review_evidence.json`。

> 历史教训：这些页面曾经是渲染器里的字符串字面量。换主题后，一篇影像组学 deck 的
> PICOS 页仍显示「肝细胞癌患者」，核心发现里仍出现「MVI 预测」「TACE 应答预测」。
> 派生之后，deck 只可能陈述综述真正测到的内容。

**主题分桶必须针对本次检索定制**：脚本内置的是通用默认桶，
先跑一轮看各桶占比，再用 `--topics-file buckets.json` 传入定制桶（JSON 对象 `{"桶名": "正则"}`）。
**所有短词/缩写一律加 `\b`。**

> ⚠️ **不要用检索式的核心词做分桶**。核心词（如 radiomics 检索里的 radiomics）
> 会命中 90% 以上的文献，桶占比接近 100%，不构成任何分布信号。
> 脚本会把占比 ≥ 80% 的桶自动标记为 `scope: "core"`，分布图只画 `specific` 桶，
> 核心词桶降级为脚注说明。定桶时同理：桶的正则应该是**区分性特征**
> （方法学、研究设计、技术分支），而不是主题本身。

#### 6.2 渲染单文件 HTML deck

```bash
"$PY" "<SKILL_DIR>/scripts/deck_build.py" \
  --content "<workspace>/output/deck_content.json" \
  --out "<workspace>/output/<主题>_deck.html"
```

综述层已内嵌在 `deck_content.json` 中，**无需再传 `--review`**（重复传入时以显式文件为准，
两者通常就是同一份 JSON）。

输出为**静态单文件 HTML**：无 CDN、无外部字体、无图表库，图表全部是内联 SVG。
翻页运行时已内置：`← / →`、`Home / End`、`空格`、滚轮、触屏滑动、底部页码块跳转、
`G` 打开页格索引、`Esc` 关闭。`Ctrl+P` 可直接打印为 PDF（每页一张）。

#### 6.3 运行版式校验（强制）

```bash
"$PY" "<SKILL_DIR>/scripts/deck_validate.py" "<workspace>/output/<主题>_deck.html" --strict
```

- **P0 必须为 0** 才可交付；存在 P0 时先修 HTML 再重新校验，**不得直接交付**。
- P1 需逐条确认；需要放宽时在答复中说明理由，必要时加 `--strict` 让 P1 也阻断。
- P0 覆盖：调色板外颜色、圆角/阴影/渐变、字号 < 13px、外部资源引用、未知版式。
- P1 覆盖：禁用字重与斜体、标题居中、页眉页脚页码缺失、警示色超限、文献卡片超 4 张、
  **F14 综述层不完整（有 M13 却缺 M14/M18）**、**F15 M13 的 PICOS 为占位内容**。

> F14 / F15 是专为「deck 与综述脱节」加的：F14 在人工删改 HTML 导致综述页残缺时报错，
> F15 在证据底座未携带 PICOS（M13 退回占位符）时报错。二者都是 P1，
> **配合 `--strict` 即成为交付阻断**。

#### 6.4 生成可编辑 `.pptx`

HTML deck 是视觉稿；**默认必须产出**可编辑 `.pptx`（无需用户另行要求），
**按平台规范交由 `tencent-pptx` 技能生成**，
不要用脚本硬转。输入材料用 `output/deck_outline.md`（**已含综述层**）或 `deck_content.json`，
并要求其遵守同一套医学深蓝规范：

> 医学专业 + 科研科技视觉方向；主色医学深蓝 `#0A3D7C`；
> 瑞士网格版式：16 列网格、直角色块、1px 发丝线、无阴影、无渐变、无圆角；
> 字号阶梯见 `references/deck-theme.md`；页面顺序与每页内容见 `deck_outline.md`；
> 标题一律左对齐贴网格线，不居中。

**PPT 必须覆盖 `deck_outline.md` 的全部页面，其中标注「【综述层】」的 8 页不得省略。**
若 PPT 页数与 outline 页数不一致，以 outline 为准补齐，并在答复中说明差异原因。

##### ⚠️ SlideDSL 写入与校验的四个高频坑

`.pptx` 由平台的 `slidep` 工具链按页写入（`upsert-dsl --page-index <0基>`，
省略或 `-1` 表示追加）。以下四点都是实际踩过的：

1. **`upsert-dsl` 会静默失败。** 它可能返回 `Error: /localapi/keyframe HTTP 500:
   presentation is not open`，而**批量循环不会因此中断**——后续每一页都退化成「追加」，
   最终页序全乱。**写入后必须回读校验页序**：解析 `.pptx` 的
   `ppt/slides/slide{N}.xml` 中 `<a:t>` 文本，逐页比对标题是否与 `deck_outline.md` 一致。
   发现错位时**重建尾部**：先追加最后一页，再用 `--page-index` 从后往前逐页覆盖。
2. **元素不得溢出父容器。** 条形图的宽度要留出父容器余量，
   否则 lint 报 P0 `child containment overflow`（实测 `right+89px` / `+91px` / `+79px`）。
   竖向同理，表格行 `padding` 过大或段落过长会报 `Bottom+36px`。
   压缩手段：减小条宽、收 `padding`、降 `lineHeight`、删冗余句。
3. **不是所有 CSS 属性都支持。** `marginTop: 'auto'` 与 `lineSpacing` 会让 lint 失败；
   改用 `justifyContent: 'space-between'` 等 flex 属性实现同效果。
   版式仅支持 flexbox（**无 grid、无 `calc()`**），画布固定 1280×720，
   换行用 `<br />`，行内样式用 `<span style>`，**不支持 `<strong>` / `<em>`**。
4. **`slidep screenshot` 在 Windows 上不可用**（报
   `The argument 'filename' must be a file URL object`，疑似要求 Linux 路径）。
   改用**直接解析 `.pptx` XML** 来验收内容与页序，不要卡在截图上。

#### 6.5 提交

用 `present_files` **一次性**展示：系统综述 `.docx`、Markdown 源文件、
HTML deck、`.pptx`、`review_evidence.json` 与 `pubmed_results.csv`。
并在答复中说明：

- 命中量、时间口径（EDAT）；
- 这是**全文复核前**的证据图谱；计数、分级与定量汇总均基于题录与摘要；
- PROBAST 与 GRADE 尚未完成，已以占位表列出；
- 所有引用 PMID 均可回查 CSV；
- deck 页数与校验结果（P0/P1/P2 计数），并说明综述层已包含在 deck 与 PPT 中；
- 主题分桶可多重归类的口径提示。

> **一键串联**：`pubmed_cli.py` 加了 `--deck` / `--review` / `--full` 参数。
> `--full` 的执行顺序为 **检索 → 综述（证据底座 + 骨架）→ deck（含综述层）**：
> ```bash
> "$PY" "<SKILL_DIR>/scripts/pubmed_cli.py" -f query.txt -s "2021/01/01" -e "2026/10/02" \
>   -o "<workspace>/output/pubmed_results.csv" \
>   --criteria-file output/criteria.json --picos-file output/picos.json \
>   --review-themes-file output/themes.json \
>   --full --deck-topic "<检索主题>"
> ```
> 其后仍需：填写 WRITE-BLOCK（5.3）→ 质检（5.4）→ 排版 `.docx`（5.5）；
> deck 侧还需 6.3 校验与 6.4 产出 `.pptx`。
>
> `--full` 走的是**同一条纳入标准守卫**，且守卫**在检索发起前**执行：
> 判据不合规时该命令直接以 exit 2 中止，`-o` 指定的旧 CSV 与 deck 内容模型**不会被覆盖**。
> 因此**不要**为了试探而先跑一次 `--full`——主题非肝脏且未提供 `--criteria-file` 时，
> 中止是预期行为，按生成的模板补文件即可。

## 依赖

```bash
pip install requests pandas
```

WorkBuddy 环境下优先使用托管 venv（见 Phase 0），依赖通常已就绪。
Phase 5 的 `review_evidence.py` / `review_compose.py` / `review_check.py` 只用标准库 + pandas；
综述排版 `.docx` 走平台文档能力。
Phase 6 的 `deck_content.py` / `deck_build.py` / `deck_validate.py` **同样只用标准库 + pandas**,
不引入新依赖；`.pptx` 由平台 PPT 能力产出，脚本侧不需要 `python-pptx`。

## 注意事项

1. **检索式确认**: 执行前必须向用户展示检索式并确认
2. **布尔优先级**: 混用 `AND`/`OR` 必须加括号
3. **日期口径**: 默认 `edat`（入库日期），需在答复中明示
4. **API 速率**: 脚本内置 0.4s 延迟，批量检索时注意耗时
5. **结果上限**: PubMed E-utilities 单次最多返回约 10,000 条
6. **日期格式**: 严格使用 `YYYY/MM/DD`
7. **PMID 校验**: 引用前必须回查，杜绝编造
8. **阶段顺序不可颠倒**: **Phase 5（系统综述）必须先于 Phase 6（deck）完成**。
   deck 的综述层全部派生自 `review_evidence.json`，而交给 PPT 环节的
   `deck_outline.md` 在 deck 阶段写出；先出 deck 再补综述，PPT 素材必然缺整层综述，
   M13 也会退回文档里写死的人群描述。
9. **deck 配色是白名单**: Phase 6 的颜色、字号、版式都锁死在规范文件里，
   不得临时自定义 hex；版式全集为 M01–M20，其中 M13–M20 为综述层页面。
   改配色必须同步改 `references/deck-theme.md` 与 `assets/deck/template-medical.html` 的 `:root`
10. **deck 校验门槛**: `deck_validate.py` 的 P0 必须为 0 才能交付；
    建议直接加 `--strict`，让 F14/F15（综述层残缺、PICOS 占位）也成为阻断
11. **综述层必须派生、不得写死**: M13/M15/M16/M17/M18/M19/M20 的内容一律从
    `review_evidence.json` 现算。文献渲染器里**不得出现任何主题专属的疾病名、终点名或人群描述**——
    这类字面量换主题后不会报错，只会悄悄输出错误结论。
12. **Phase 5 证据分级为暂定**: 研究设计与证据等级由摘要中报告的方法学信息自动推断，
    全文复核后应更新；PROBAST、GRADE 与 RoB 评估需人工完成，不得用推断填充
13. **题录筛选不等于全文筛选**: PRISMA 流程中的「潜在纳入」是题录层面的计数，
    真正的「已纳入」必须在全文复核后确定
14. **Phase 5/6 自动串联**: 检索完成后先系统综述、再 deck（HTML + PPTX），**默认自动执行**，
    不询问用户；仅当用户本次请求明确不要时才跳过，并在答复中说明。
15. **纳入标准必须按主题定制**: `--criteria-file` 与 `--picos-file` 是**必填项**。
    脚本内置的是肝细胞癌专用判据，用于其他主题会静默误排除；
    非肝脏主题未提供定制文件时脚本**直接中止（exit 2）**并生成模板，
    这是有意为之的保护，不要用 `--allow-default-*` 绕过。
    跑完先核对 `eligible / identified` 比例（正常约 80%，过低说明判据没对齐）。
16. **PICOS 随证据底座传递**: `--picos-file` 的内容会写入 `review_evidence.json` 的
    `meta.picos`，deck 的 M13 页直接读它。**不要**另建一份给 deck 用的 PICOS 副本，
    两份必然漂移。
17. **图表编号以源文件为唯一权威**: 排版阶段必须保留 `review_compose.py` 派生的表号，
    渲染器不得按出现顺序重新编号，否则会与附录 A 核对表脱节（`review_check.py` R20 会拦截）。
18. **`.pptx` 写入后必须回读校验页序**: `slidep upsert-dsl` 可能静默失败导致页序错乱，
    验收以 `.pptx` XML 解析结果为准；`slidep screenshot` 在 Windows 下不可用。
19. **不要用剪辑式折衷掩盖失败**: 若某阶段确认无法完成（如排版脚本缺失），
    明确告知用户并给出可复现的命令，而不是交付一个看起来完整但内容错位的产物。

## 常见问题

| 问题 | 处理方式 |
|------|----------|
| 结果为空 | 检查检索式语法；放宽条件；扩大时间范围 |
| 结果太多 | 添加限定词；缩小时间；限定文献类型 |
| 结果太少/漏检 | 检查是否误用 `AND` 收紧了同义词组；去掉领域限定词；补 MeSH 词 |
| 需要更精确 | 使用 MeSH 主题词 `term[MeSH Major Topic]` |
| 下载全文 | PubMed 仅提供元数据；通过 DOI 链接跳转出版商 |
| deck 打不开/白屏 | 单文件需在浏览器直接打开并允许本地脚本；不要放进沙箱 iframe |
| deck 某页内容溢出 | M06 条形 >10 条、M08 分桶 >8 条时先减项，或拆成两页 |
| **PPT 里没有综述内容** | 顺序错了：`deck_outline.md` 是 PPT 的唯一素材，须先跑 Phase 5 再做 deck；确认 `deck_content.py` 带了 `--review`，outline 顶部应显示「综述层：已包含」 |
| **deck 的 PICOS 页人群与本主题无关** | 证据底座未携带 PICOS（M13 退回占位符或旧字面量）。给 `review_evidence.py` 补 `--picos-file` 重跑证据底座，再重建 deck；`deck_validate.py` 的 F15 会提示 |
| 要导出 PDF | 浏览器打开 deck → Ctrl+P → 边距「无」→ 每页一张（16:9 已设 `@page`） |
| 想让 deck 换主题色 | 改 `references/deck-theme.md` 与模板 `:root` 两处，再跑 `deck_validate.py` |
| 校验报 P0 调色板外颜色 | 把该 hex 换成 `deck-theme.md` 第 2 节的 token；确需新色则先登记进白名单 |
| 脚本路径报错 | 用 Glob 确认 `pubmed_cli.py` 实际位置，勿硬编码 `.claude/skills/...` |
| `ModuleNotFoundError` | 切到 WorkBuddy 托管 venv，勿改系统环境 |
| `tail` 后看不到统计 | `tail` 会截掉开头统计段；勿截断或改读 CSV 自行统计 |
| 分桶占比合计超 100% | 属正常（可多重归类），需在报告中标注口径 |
| 聚类关键词虚高 | 检查子串陷阱，短词加 `\b`（如 `spect`→`\bspect\b`） |
| `[review_evidence] 已中止：…非肝脏主题`（exit 2） | 正常保护。按生成的 `criteria_template.json` 填写后加 `--criteria-file` 重跑 |
| `[review_compose] 已中止：…肝细胞癌 PICOS`（exit 2） | 同上，改填 `picos_template.json` 后加 `--picos-file` |
| 综述里出现与主题无关的疾病名/受体名 | 内置肝细胞癌 PICOS 泄漏。补 `--picos-file`，并重跑 5.2 |
| 「潜在纳入」数量异常少（< 检索量一半） | 判据未按主题定制，被静默误排除；先查 `criteria.json` |
| R14 表编号不连续 / 表号引用悬空 | 结果表缺 `**表 N　标题**` 表题；检查 compose 是否漏发 caption |
| R20 PRISMA 核对表指向不符 | 核对表定位映射与正文表号脱节；表号须统一由 `T_*` 常量派生 |
| 排版后表格编号与附录引用对不上 | 渲染器按位置重排了表号；改为向前取表题、保留原编号 |
| F14 综述层不完整 | HTML 里综述页被删或未被渲染；重跑 `deck_content.py --review` 后重建 deck |
| `slidep` 报 `presentation is not open` | 写入静默失败；回读 `.pptx` XML 校验页序并重建尾部 |
| `.pptx` 某页元素溢出 | 条形宽超父容器 / 行 padding 过大；减宽度、收 padding、降 lineHeight |
| `slidep screenshot` 报 filename 错误 | Windows 已知问题；改用解析 `.pptx` XML 验收 |
| `setup-html-to-docx.sh` 静默不装依赖 | Windows 硬编码 `bin/python`；直接用 `Scripts/python.exe` 装 requirements |

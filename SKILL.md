---
name: pubmed-retrieve
description: Use whenever the user wants to search for or retrieve literature in biomedicine and clinical medicine — including but not limited to clinical trials, systematic reviews, meta-analyses, evidence-based medicine, drug and treatment research, surgery, internal medicine, cardiology, oncology, neurology, psychiatry, pediatrics, obstetrics & gynecology, emergency medicine, radiology, pathology, nursing, public health, epidemiology, genetics, immunology, microbiology, pharmacology, physiology, anatomy, or any other life-sciences discipline. Generates a PubMed query, executes the search, produces a summary table, and can render the results into an academic report deck (single-file HTML slides plus an editable PPTX) in a medical deep-blue Swiss grid style.
---

# PubMed Retrieve Skill

根据用户需求生成 PubMed 检索式，调用 `scripts/` 下的脚本执行检索，生成文献汇总表；
用户需要汇报时，还可把检索结果渲染成学术汇报 deck（单文件 HTML + 可编辑 PPTX）。

## 路径约定

本 skill 的脚本位于 **本 SKILL.md 所在目录**下的 `scripts/`。请以 skill 目录为基准定位脚本，不要硬编码 `.claude/skills/...` 这类路径。

| 子目录 | 内容 |
|--------|------|
| `scripts/` | `pubmed_cli.py`（检索 CLI）、`pubmed_script.py`（E-utilities 实现）、`deck_content.py` / `deck_build.py` / `deck_validate.py`（Phase 5 deck 链路） |
| `assets/deck/` | `template-medical.html`（医学深蓝瑞士风单文件 deck 模板） |
| `references/` | `deck-theme.md`（配色/字号/网格规范）、`deck-layouts.md`（M01–M12 版式契约） |

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

### Phase 4: 提交

用 `present_files` 一次性展示报告与 CSV。在最终答复中复述：命中量、时间口径（EDAT）、
关键分布数字、主要趋势，并说明"PubMed 仅提供题录与摘要元数据，全文需经 DOI 跳转出版商"。

如果用户还要学术汇报 PPT，继续走 Phase 5。

---

### Phase 5: 生成学术汇报 PPT（用户要求时执行）

把检索结果转成一份**可汇报的学术 deck**。视觉方向固定为 **「医学专业 + 科研科技」**，
采用**瑞士国际主义**方法论（16 列网格、直角色块、1px 发丝线、极致字号对比、
无阴影无渐变无圆角），主色**医学深蓝 `#0A3D7C`**。

设计依据（**生成前必读，不要凭记忆发挥**）：

| 文件 | 内容 |
|------|------|
| `references/deck-theme.md` | 调色板白名单、字体栈、网格与安全边距、字号阶梯、禁止清单 F01–F12 |
| `references/deck-layouts.md` | M01–M12 锁定版式契约、`deck_content.json` 字段定义、内容映射与写作规则 |

**交付两件**：① 单文件 HTML deck（高保真、可翻页演示、可打印为 PDF）；② 可编辑 `.pptx`。

#### 5.1 生成内容模型 `deck_content.json`

```bash
PY="$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"   # 见 Phase 0

"$PY" "<SKILL_DIR>/scripts/deck_content.py" \
  --csv "<workspace>/pubmed_results.csv" \
  --out-dir "<workspace>/output" \
  --topic "<检索主题，≤30 字>" \
  --query-file "<workspace>/.workbuddy/tmp_query.txt" \
  --start "2021/01/01" --end "2026/10/02" --max-results 2000 \
  --search-date "<今天 YYYY-MM-DD>"
```

产出 `output/deck_content.json`（唯一数据源）与 `output/deck_outline.md`（逐页大纲，
同时是交给 PPT 生成环节的素材）。

**主题分桶必须针对本次检索定制**：脚本内置的是通用默认桶，
先跑一轮看各桶占比，再用 `--topics-file buckets.json` 传入定制桶（JSON 对象 `{"桶名": "正则"}`）。
**所有短词/缩写一律加 `\b`。**

> ⚠️ **不要用检索式的核心词做分桶**。核心词（如 radiomics 检索里的 radiomics）
> 会命中 90% 以上的文献，桶占比接近 100%，不构成任何分布信号。
> 脚本会把占比 ≥ 80% 的桶自动标记为 `scope: "core"`，分布图只画 `specific` 桶，
> 核心词桶降级为脚注说明。定桶时同理：桶的正则应该是**区分性特征**
> （方法学、研究设计、技术分支），而不是主题本身。

#### 5.2 渲染单文件 HTML deck

```bash
"$PY" "<SKILL_DIR>/scripts/deck_build.py" \
  --content "<workspace>/output/deck_content.json" \
  --out "<workspace>/output/<主题>_deck.html"
```

输出为**静态单文件 HTML**：无 CDN、无外部字体、无图表库，图表全部是内联 SVG。
翻页运行时已内置：`← / →`、`Home / End`、`空格`、滚轮、触屏滑动、底部页码块跳转、
`G` 打开页格索引、`Esc` 关闭。`Ctrl+P` 可直接打印为 PDF（每页一张）。

#### 5.3 运行版式校验（强制）

```bash
"$PY" "<SKILL_DIR>/scripts/deck_validate.py" "<workspace>/output/<主题>_deck.html"
```

- **P0 必须为 0** 才可交付；存在 P0 时先修 HTML 再重新校验，**不得直接交付**。
- P1 需逐条确认；需要放宽时在答复中说明理由，必要时加 `--strict` 让 P1 也阻断。
- P0 覆盖：调色板外颜色、圆角/阴影/渐变、字号 < 13px、外部资源引用、未知版式。
- P1 覆盖：禁用字重与斜体、标题居中、页眉页脚页码缺失、警示色超限、文献卡片超 4 张。

#### 5.4 生成可编辑 `.pptx`

HTML deck 是视觉稿；需要可编辑文件时，**按平台规范交由 `tencent-pptx` 技能生成**，
不要用脚本硬转。输入材料用 `output/deck_outline.md`（或 `deck_content.json`），
并要求其遵守同一套医学深蓝规范：

> 医学专业 + 科研科技视觉方向；主色医学深蓝 `#0A3D7C`；
> 瑞士网格版式：16 列网格、直角色块、1px 发丝线、无阴影、无渐变、无圆角；
> 字号阶梯见 `references/deck-theme.md`；页面顺序与每页内容见 `deck_outline.md`；
> 标题一律左对齐贴网格线，不居中。

#### 5.5 提交

用 `present_files` **一次性**展示 HTML deck 与 `.pptx`，并在答复中说明：
命中量、时间口径（EDAT）、deck 页数、校验结果（P0/P1/P2 计数）、
以及主题分桶可多重归类的口径提示。

> **一键串联**：`pubmed_cli.py` 加了 `--deck` / `--deck-topic` 参数，
> 检索完成后自动跑 5.1 + 5.2，可省去手工调用：
> ```bash
> "$PY" "<SKILL_DIR>/scripts/pubmed_cli.py" -f query.txt -s "2021/01/01" -e "2026/10/02" \
>   -o "<workspace>/output/pubmed_results.csv" \
>   --deck --deck-topic "radiomics 在肝细胞癌预后预测中的应用"
> ```
> 校验（5.3）与 `.pptx`（5.4）仍需单独执行。

## 依赖

```bash
pip install requests pandas
```

WorkBuddy 环境下优先使用托管 venv（见 Phase 0），依赖通常已就绪。
Phase 5 的 `deck_content.py` / `deck_build.py` / `deck_validate.py` **只用标准库 + pandas**，
不引入新依赖；`.pptx` 由平台 PPT 能力产出，脚本侧不需要 `python-pptx`。

## 注意事项

1. **检索式确认**: 执行前必须向用户展示检索式并确认
2. **布尔优先级**: 混用 `AND`/`OR` 必须加括号
3. **日期口径**: 默认 `edat`（入库日期），需在答复中明示
4. **API 速率**: 脚本内置 0.4s 延迟，批量检索时注意耗时
5. **结果上限**: PubMed E-utilities 单次最多返回约 10,000 条
6. **日期格式**: 严格使用 `YYYY/MM/DD`
7. **PMID 校验**: 引用前必须回查，杜绝编造
8. **deck 配色是白名单**: Phase 5 的颜色、字号、版式都锁死在规范文件里，
   不得临时自定义 hex，也不得发明 M01–M12 之外的版式；改配色必须同步改
   `references/deck-theme.md` 与 `assets/deck/template-medical.html` 的 `:root`
9. **deck 校验门槛**: `deck_validate.py` 的 P0 必须为 0 才能交付

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
| 要导出 PDF | 浏览器打开 deck → Ctrl+P → 边距「无」→ 每页一张（16:9 已设 `@page`） |
| 想让 deck 换主题色 | 改 `references/deck-theme.md` 与模板 `:root` 两处，再跑 `deck_validate.py` |
| 校验报 P0 调色板外颜色 | 把该 hex 换成 `deck-theme.md` 第 2 节的 token；确需新色则先登记进白名单 |
| 脚本路径报错 | 用 Glob 确认 `pubmed_cli.py` 实际位置，勿硬编码 `.claude/skills/...` |
| `ModuleNotFoundError` | 切到 WorkBuddy 托管 venv，勿改系统环境 |
| `tail` 后看不到统计 | `tail` 会截掉开头统计段；勿截断或改读 CSV 自行统计 |
| 分桶占比合计超 100% | 属正常（可多重归类），需在报告中标注口径 |
| 聚类关键词虚高 | 检查子串陷阱，短词加 `\b`（如 `spect`→`\bspect\b`） |

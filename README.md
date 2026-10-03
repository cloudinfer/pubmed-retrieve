# pubmed-retrieve

> **从一句中文研究需求，到一份可投稿的系统综述 + 一套汇报 PPT。**
> 检索、去重、筛选、分级、成文、排版、质检——全在 AI 助手里一句话跑完。

面向生物医学研究者、临床医生与研究生。你负责提问题与做判断，机器负责最耗时的那 80%。

---

## 你大概正在经历这些

| 痛点 | 现实 | 本技能 |
|---|---|---|
| **检索式写不对** | 漏 MeSH、混用 AND/OR 不加括号、同义词组不全 → 漏检关键文献，或命中上万条无从下手 | 自然语言 → 专业检索式（布尔逻辑 + 字段限定 + MeSH + 文献类型），**执行前请你确认** |
| **几百上千条题录，人工筛到崩溃** | 逐条读标题摘要、做取舍、还得保持判据一致 | 按你定制的判据自动完成题录级筛选，**每条排除理由可追溯** |
| **PRISMA 流程图画不出、数字对不上** | 识别/去重/排除/纳入四个数总有一处错，审稿人一眼就看出来 | 计数全由脚本现算，`识别 − 题录排除 = 全文评估` 自动自洽校验（R11） |
| **系统综述写作门槛高** | 章节不全、引用乱标、数字与结果打架、格式反复改 | 确定性章节与全部表格由脚本产出，叙述只留**带必引文献清单的写作块** |
| **参考文献手工编号必错** | 加一条、删一条，全文编号全乱 | Vancouver 格式**全自动编号**，每条附 PMID 可回查 |
| **做完综述还要再做 PPT** | 内容对不上、复制粘贴、排版重来一遍 | 综述直接渲染成 PPT，**综述页全程同源派生**，不可能自相矛盾 |

> 这不是"帮你搜点文献"，是把系统综述这条产线的体力活全部接管。

### 实测效果（一次真实运行）

以「医学影像生境分析」为主题，检索 EDAT 2026/04/03–2026/10/03：

| 环节 | 结果 |
|---|---|
| 检索命中 | 198 篇，10 种期刊 |
| 题录筛选 | 排除 43 篇，**潜在纳入 152 篇**（含 5 类可追溯排除理由） |
| 证据底座 | 逐篇暂定分级、定量信号抽取、7 个主题收敛汇总、8 项研究空白 |
| 综述骨架 | 5 章 31 小节、表 1–6、参考文献自动编号，24 个写作块待填 |
| 汇报 deck | 21 页（含 8 页综述层 + 4 页分析层），校验 **P0 = 0** |

---

## 它能交付什么

一次完整运行（`--full`）产出三层成品：

```
① 检索结果集   pubmed_results.csv       结构化题录：PMID/标题/作者/期刊/DOI/摘要
                ↓
② 系统综述     review_draft.md           PRISMA 2020 骨架 + 参考文献 + 全部表格
               review_evidence.json      证据底座：计数/分级/定量信号/收敛/空白
               review_corpus.md          代表文献摘要集
                ↓
③ 汇报材料     deck.html                 单文件网页 PPT，浏览器直接放映、可导 PDF
               deck_outline.md           PPT 唯一素材（已含综述层）
               医学…汇报.pptx            可编辑 PowerPoint
```

### 阶段一 · 检索：自然语言直出专业检索式

```pubmed
--topic "SGLT2抑制剂治疗心力衰竭"
→ (SGLT2 inhibitor OR SGLT-2 inhibitor OR "sodium-glucose cotransporter 2 inhibitor")
  AND ("heart failure" OR HF) AND "clinical trial"[pt]
```

输出 CSV 含 9 个字段（PMID、ISSN、标题、作者、期刊、日期、DOI、摘要…），
终端同步打印**期刊分布 Top10 / 年份分布 / 文献列表**。

### 阶段二 · 系统综述：可投稿级产出，不是"综述风格的总结"

严格按 **PRISMA 2020 + TRIPOD** 规范组织，覆盖 27 个条目：

- **证据底座自动现算**：筛选计数、逐篇暂定证据等级、定量信号（AUC / HR / 样本量 / 外部验证）、主题收敛汇总、研究空白
- **骨架由脚本写死结构**：章节 1–5 与小节 1.1–5.6 全部生成，叙述部分留写作块并**附带该段必引的 PMID 清单**——从机制上杜绝"编引用"
- **参考文献全自动**：Vancouver 格式、顺序编号、PMID 附注，禁止手抄
- **质检器 R01–R20 把关**：

| 拦截项 | 例子 |
|---|---|
| 引用越界 / 无引用段落 | 连续 300 字没有一条引用、引用编号超过参考文献总数 |
| **数字与证据底座不一致** | 正文写"纳入 152 篇"、底座其实是 149 → P0 |
| **表号连续性 + 交叉引用语义** | "见表 2"实际指向表 3、表号跳号 → P0 |
| 绝对化表述 | "证明了""显著优于""首次证明" |
| 残留占位符 / 字数不足 | 系统综述正文 < 12000 字 |

**一个真实的设计教训**：早期版本把肝细胞癌的筛选判据写进了脚本。换主题后它**不报错**，
只是静默筛掉 395 条中的 374 条，综述骨架里还冒出与主题无关的疾病名。
现在改成——**脚本不内置任何主题的判据**，`--criteria-file` 与 `--picos-file` 必填，
缺文件即中止并生成可编辑模板。**宁可停下来要你填，也不悄悄输出错东西。**

### 阶段三 · 汇报 deck：医学深蓝瑞士网格风

把**系统综述**渲染成一套能直接讲的 PPT：

- 单文件 HTML：无依赖，`← / →` 翻页、`G` 页格索引、`Ctrl+P` 导 PDF
- 可编辑 .pptx：交给平台 PPT 能力生成，保留完整可编辑性
- **版式体系 M01–M24**（当前实现 22 种），其中：
  - **M13–M20 综述层**：PICOS、PRISMA 漏斗、证据等级、收敛汇总、研究空白、核心发现、结论
  - **M21–M24 分析层**：**临床问题图谱 / 数据模态分布 / 技术路线格局 / 评价方法报告率**
- 视觉规范锁死：医学深蓝 `#0A3D7C`、直角色块、1px 发丝线、无阴影无渐变
- 校验器 **F01–F15** 把关，含两条专项拦截：
  - **F14** 综述层残缺
  - **F15** PICOS 页退回占位（防止 deck 说出与综述不同的人群）

**顺序契约（重要）**：deck 的综述层派生自 `review_evidence.json`，
因此**必须先跑综述、再跑 deck**。这条顺序由 CLI 强制，不是建议。
（反例：一篇影像组学 deck 的 PICOS 页曾显示"肝细胞癌患者"——正是综述层缺失、
渲染器退回写死字面量的后果。）

---

## 快速开始

### 1. 安装

**依赖**：Python 3.8+、`requests`、`pandas`

```bash
pip install requests pandas
```

**安装为 Skill**：

```bash
# WorkBuddy
git clone https://github.com/cloudinfer/pubmed-retrieve.git \
  ~/.workbuddy/skills/pubmed-retrieve/

# Claude Code
git clone https://github.com/cloudinfer/pubmed-retrieve.git \
  ~/.claude/skills/pubmed-retrieve/
```

> 在 WorkBuddy 中运行时无需手动配置：技能会自动使用隔离的托管虚拟环境，
> 缺失依赖时自动安装，不污染系统 Python。

### 2. 使用

```
/pubmed-retrieve <用中文描述你的研究需求>
```

**最省事的一条命令**（检索 → 综述 → deck 全自动）：

```bash
python scripts/pubmed_cli.py -f query.txt -s 2021/01/01 -e 2026/10/02 \
    -o output/pubmed_results.csv \
    --criteria-file output/criteria.json --picos-file output/picos.json \
    --review-themes-file output/themes.json \
    --full --deck-topic "影像组学文献调研"
```

> 首次运行时若未提供判据文件，脚本会中止并写出模板
> （`criteria_template.json` / `picos_template.json`）——
> 按注释填好主题专属判据，重跑即可。字段说明见 [`references/review-criteria.md`](references/review-criteria.md)。

### 3. 只想要文献列表？

```bash
/pubmed-retrieve 找10篇关于阿尔茨海默病淀粉样蛋白假说的最新文献
```

生成检索式 → 确认 → 命中 6699 条，取前 10 条 → 输出 CSV。
不想要综述和 PPT 就直接说，**默认不会强塞给你**。

---

## 分步执行（想介入中间环节）

```bash
# 阶段一：检索
python scripts/pubmed_cli.py -f query.txt -s 2021/01/01 -e 2026/10/02 \
    -o output/pubmed_results.csv

# 阶段二：证据底座 → 综述骨架 → 质检
python scripts/review_evidence.py --csv output/pubmed_results.csv --out-dir output \
    --topic "<主题>" --query-file query.txt \
    --criteria-file output/criteria.json --picos-file output/picos.json \
    --themes-file output/themes.json --start 2021/01/01 --end 2026/10/02

python scripts/review_compose.py --evidence output/review_evidence.json \
    --csv output/pubmed_results.csv --out-dir output \
    --topic "<主题>" --picos-file output/picos.json

python scripts/review_check.py output/review_draft.md \
    --evidence output/review_evidence.json --refmap output/review_refmap.json --strict

# 阶段三：deck
python scripts/deck_content.py --csv output/pubmed_results.csv --out-dir output \
    --topic "<主题>" --query-file query.txt \
    --review output/review_evidence.json --start 2021/01/01 --end 2026/10/02
python scripts/deck_build.py    --content output/deck_content.json --out output/deck.html
python scripts/deck_validate.py output/deck.html --strict
```

每个质检器都以 **P0 = 0** 为交付门槛。

---

## 目录结构

```
pubmed-retrieve/
├── SKILL.md                     技能主文档：三阶段全流程与硬性约束
├── scripts/                     8 个脚本，纯标准库 + requests/pandas，无重型依赖
│   ├── pubmed_cli.py            检索主入口（含 --full 一键串联）
│   ├── pubmed_script.py         检索执行核心（esearch / efetch / 解析 / 落盘）
│   ├── review_evidence.py       证据底座（PRISMA 计数 / 分级 / 定量信号 / 收敛 / 空白）
│   ├── review_compose.py        综述骨架（章节、表格、参考文献、写作块）
│   ├── review_check.py          综述质检器（R01–R20）
│   ├── deck_content.py          内容模型（描述层 + 分析层 M21–M24 + 综述层）
│   ├── deck_build.py            HTML deck 渲染（M01–M24）
│   └── deck_validate.py         deck 校验器（F01–F15）
└── references/
    ├── review-standard.md       期刊发表级综述规范（PRISMA 27 项落地映射）
    ├── review-criteria.md       纳入标准与 PICOS 定制指南（含完整示例）
    ├── deck-layouts.md          版式契约（M01–M24）与页序规则
    └── deck-theme.md            配色/字号/网格规范（改色白名单）
```

---

## 设计原则

1. **宁可中止，不输出错的东西**：判据缺失、顺序颠倒、综述层残缺——一律报错并给出修复路径，绝不静默降级。
2. **数字只有一个来源**：所有计数从 `review_evidence.json` 现算，正文数字与底座不一致会被质检器拦下。
3. **综述层不得写死**：deck 的综述页必须派生自证据底座，禁止在渲染器里写主题专属字面量——换主题后它不会报错，只会悄悄说错话。
4. **图表编号以脚本为唯一权威**：排版阶段不得按出现顺序重新编号。

---

## 常见问题

**Q：必须联网吗？**
A：检索阶段需要（NCBI E-utilities）。若已有 CSV，可直接从阶段二开始。

**Q：数据会不会被上传？**
A：不会。脚本只调用 PubMed 官方 API，所有文件都落在你本地。

**Q：能用于非医学主题吗？**
A：可以。检索与 deck 与主题无关；系统综述部分需按主题填写判据文件——
这正是把判据从脚本里拿出来的原因。

**Q：检索太多/太少怎么办？**
A：加限定词缩小范围，或检查同义词组是否被 `AND` 误收紧。脚本会先请你确认检索式。

**Q：PPT 能改成别的配色吗？**
A：可以，但需同时改 `references/deck-theme.md` 与模板 `:root`，再跑校验器。

---

## PubMed 检索语法参考

| 语法 | 示例 |
|------|------|
| 布尔逻辑 AND/OR/NOT | `diabetes AND exercise NOT pediatric` |
| 字段限定 | `"machine learning"[Title/Abstract]` |
| MeSH 主题词 | `diabetes mellitus[MeSH]` |
| 文献类型 | `clinical trial[pt]` / `review[pt]` |
| 精确短语 | `"physical activity"` |
| 通配符 | `Alzheimer*` |

**速率限制**：NCBI 约 3 次/秒，脚本内置 0.4 秒请求间隔；单次检索上限约 10,000 条。

---

## 许可证

[Apache License 2.0](./LICENSE)

## 联系与交流

有问题或建议欢迎提 Issue，也欢迎扫码加微信交流。

![联系方式](./wechat.jpg)

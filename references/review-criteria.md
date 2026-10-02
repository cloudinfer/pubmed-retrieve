# 纳入标准与 PICOS 定制指南

Phase 6 的两套输入文件——`--criteria-file`（筛选判据，正则）与 `--picos-file`（成文措辞）——
的字段定义、写法规范与完整示例。

---

## 1. 为什么必须定制

`review_evidence.py` 与 `review_compose.py` 内置的纳入标准**描述的是肝细胞癌**，
是早期一次肝脏主题任务留下的默认值。把它用在其他主题上：

- **不会报错**。正则依然能编译、筛选依然会输出、综述依然会成文；
- 只会**静默排除几乎全部记录**，并在文末留下与主题无关的疾病名。

实测一次「影像组学」检索（命中 395 条）配内置判据的结果：

| 配置 | 潜在纳入 | 占比 |
|------|---------|------|
| 内置肝细胞癌判据（错误） | 14 条 | 3.5% |
| 定制影像组学判据（正确） | 313 条 | 79.2% |

同一批文献，误排除 374 条，且综述骨架的 PICO 表写着
「经病理或临床标准确诊的肝细胞癌患者」，排除理由里还出现 EphA2 受体。

因此脚本加了**守卫**：主题不含 `hepat` / `hcc` / `liver` / `hepatic` / 肝 时，
若未提供定制文件，**直接以 exit 2 中止**并写出模板文件。
`--allow-default-criteria` / `--allow-default-picos` 可显式放行（仅肝脏主题应使用）。

---

## 2. `--criteria-file`：筛选判据

控制**题录层面（题名 + 摘要）的确定性排除**，直接决定 PRISMA 漏斗的数字。

| 键 | 类型 | 作用 |
|----|------|------|
| `pop_in` | 正则 | 目标人群的**必要**信号。题名或摘要都不匹配 → 排除 |
| `pop_strong` | 正则 | 题名中出现即判定为目标人群的**强信号**，用于抵消 `other_primary` 的误伤 |
| `other_primary` | 正则 | 其他原发肿瘤。题名命中且未命中 `pop_strong` → 排除 |
| `idx_in` | 正则 | 指数检验（本次调研的方法学）。不匹配 → 排除 |
| `out_in` | 正则 | 结局（预后 / 诊断 / 疗效）。不匹配 → 排除 |
| `pop_label` | 字符串 | 排除理由中的人群名称，用于 PRISMA 表格显示 |
| `other_primary_label` | 字符串 | 其他原发肿瘤的显示名 |
| `idx_label` | 字符串 | 指数检验的显示名 |
| `out_label` | 字符串 | 结局的显示名 |

### 写法规范

1. **短词/缩写一律加 `\b`。** `\bhcc\b`、`\bcnn\b`、`\bos\b`、`\bai\b`。
   不加边界时 `ai` 会命中 "main"、"domain"，`os` 会命中 "diagnosis"。
2. **警惕子串陷阱。** 真实案例：`hepatocellular` 会命中
   *erythropoietin-producing hepatocellular receptor A2*（EphA2，一个蛋白名），
   使胶质瘤研究被判为 HCC 人群。写法：`hepatocellular(?!\s+receptor)`。
3. **`other_primary` 与 `pop_strong` 必须成对设计。** 前者是"排他"，后者是"豁免"，
   只写前者会让目标人群被邻近癌种的研究误伤（肝转移、胆道肿瘤等）。
4. **不需要排除项时用空串。** `"other_primary": ""` 即关闭该项检查。
5. **`pop_strong` 无强信号时用 `(?!)`**（永不匹配的负向前瞻），避免空正则命中一切。

### 示例（影像组学，通用肿瘤）

```json
{
  "pop_in": "tumou?r|cancer|carcinoma|neoplasm|lesion|malignan|nodule|mass",
  "pop_strong": "(?!)",
  "other_primary": "",
  "idx_in": "radiomic|radiogenomic|deep learning|machine learning|convolutional|\\bcnn\\b|artificial intelligence|\\bai\\b|nomogram|signature|texture analys|image feature",
  "out_in": "prognos|survival|recurrence|relapse|\\bpfs\\b|\\bos\\b|hazard ratio|risk stratif|outcome|predict",
  "pop_label": "目标肿瘤人群",
  "other_primary_label": "非目标原发肿瘤（题名主导）",
  "idx_label": "影像组学或影像人工智能方法",
  "out_label": "预后/诊断结局"
}
```

> 注意 JSON 中的反斜杠需要转义：正则 `\b` 在 JSON 里写成 `\\b`。

### 示例（肝细胞癌，即内置默认值）

```json
{
  "pop_in": "hepatocellular|\\bhcc\\b|liver (?:cancer|carcinoma|tumor|tumour|neoplasm)|hepatic (?:cancer|carcinoma)|\\bhepatoma\\b",
  "pop_strong": "hepatocellular(?!\\s+receptor)|\\bhcc\\b|\\bhepatoma\\b",
  "other_primary": "glioblastoma|glioma|breast cancer|lung cancer|colorectal|pancreatic|gastric cancer|prostate|cholangiocarcinoma|biliary tract|gallbladder|melanoma|renal cell|ovarian|cervical|thyroid|bladder cancer|lymphoma|leukemia|sarcoma|endometrial|head and neck",
  "pop_label": "肝细胞癌",
  "other_primary_label": "肝细胞癌（题名主导）",
  "idx_label": "影像组学或影像人工智能方法",
  "out_label": "预后结局"
}
```

---

## 3. `--picos-file`：成文措辞

只影响**综述文字**（§1.2 的 PICO 表、§2.2 的纳入排除标准表、关键词、摘要），
不影响任何计数。

| 键 | 对应位置 |
|----|---------|
| `population` | §1.2 PICO 表的「人群（P）」 |
| `index` | §1.2「指数检验（I）」 |
| `comparator` | §1.2「比较（C）」 |
| `outcome` | §1.2「结局（O）」 |
| `study_type` | §1.2「研究类型（S）」 |
| `population_in` / `population_out` | §2.2 纳入排除表「人群」行的纳入 / 排除 |
| `outcome_in` / `outcome_out` | §2.2「结局」行 |
| `keywords` | 摘要末尾的「关键词」（分号分隔） |

> §2.2 的「指数检验」「研究类型」「语言与可及性」三行目前是固定文本，
> 若本次主题的方法学与影像组学无关，需在 6.3 填写作块时一并改写。

### 示例（影像组学，通用）

```json
{
  "population": "经病理或临床标准确诊的实体肿瘤患者，不限瘤种与治疗方式",
  "population_in": "题名或摘要明确涉及实体肿瘤人群的影像组学或影像人工智能研究",
  "population_out": "原发肿瘤不明确；纯体模/动物实验；仅涉及非肿瘤性疾病",
  "index": "基于 CT / MRI / 超声 / PET 的影像组学或影像人工智能模型",
  "comparator": "传统临床病理模型、单一临床指标，或不同建模路径之间的比较",
  "outcome": "总体生存、无进展生存与复发、病理学标志物、治疗应答",
  "outcome_in": "生存、复发、病理学标志物、治疗应答中的至少一项",
  "outcome_out": "仅诊断或分期，无预后或应答终点",
  "study_type": "原始研究（含队列、病例对照）与系统综述 / Meta 分析",
  "keywords": "影像组学；影像基因组学；人工智能；预后预测；系统综述"
}
```

---

## 4. 配套文件：`--themes-file`

同一批定制文件里还应包含**分析主题**（与筛选判据无关，但决定综述 3.5 节的骨架）：

```bash
--themes-file "<workspace>/output/themes.json"
```

JSON 对象 `{"主题名": "正则"}`。要求：

- 主题应表达**主张**（这篇文献支持什么结论），而不是关键词（那属于 Phase 5 的 deck 分桶）；
- 每个主题的正则必须能覆盖足够语料（`--per-theme` 默认 8 篇），否则该主题的写作块会缺引用；
- 与 `--criteria-file` 一样，短词加 `\b`。

**Phase 5 的 deck 分桶与 Phase 6 的分析主题不得复用同一份文件**：
前者是描述性的（哪些词出现），后者是分析性的（哪些主张成立）。

---

## 5. 落盘约定

| 文件 | 建议路径 | 说明 |
|------|---------|------|
| `criteria.json` | `<workspace>/output/criteria.json` | 筛选判据，随产物一并交付以备复核 |
| `picos.json` | `<workspace>/output/picos.json` | 成文措辞 |
| `themes.json` | `<workspace>/output/themes.json` | 分析主题 |

判据来源会被记录：PICOS 来源写入综述 §2.1 正文，
筛选判据来源写入 `review_evidence.json` 的 `meta.criteria_source`。
两者都应在最终答复中说明，使 PRISMA 计数可被第三方复现。

---

## 6. 自检清单

跑完 `review_evidence.py` 后立即核对：

- [ ] `criteria=` 一行不是 `builtin-hepatocellular-carcinoma`；
- [ ] `eligible / identified` 比例合理（经验值约 0.7–0.9；显著偏低说明判据过紧或主题词没对齐）；
- [ ] PRISMA 排除理由中出现的是**本次主题**的名称，而非「肝细胞癌」；
- [ ] `review_corpus.md` 里的代表文献确实属于本次主题；
- [ ] 生成骨架后，§1.2 的 PICO 表与 §2.2 的纳入排除表读起来描述的是本次疾病；
- [ ] `picos=` 一行不是 `builtin-hepatocellular-carcinoma`。

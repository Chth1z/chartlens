# Field Coverage and Baseline Plan

This document inventories every export-template field, every schema field, and the actual coverage of the `mock_general` baseline. It is the planning ground for expanding the precision baseline beyond demographics + history + lifestyle to the full clinical extraction surface.

Status as of 2026-05-20, after E1-010 Phase B close: the rule-only baseline scores `80/80 = 1.000` on 11 synthetic fixtures, covering **12 of 22 schema fields**. Phase B added `tumor_history`. The remaining 10 fields are still completely unmeasured by the precision contract.

## Export Template Inventory

`config/export_templates/medical_inpatient_zh.yaml` declares 23 columns (the export surface that downstream Excel reports consume). Every column maps to a schema field by `field_key`.

| Order | field_key | Header | Group | Type | Allowed codes | Today's gold cases |
| ---: | --- | --- | --- | --- | --- | ---: |
| 1 | `gender` | 性别(男1，女2) | demographics | enum | `1`, `2`, unknown | 10 |
| 2 | `age` | 年龄 | demographics | number | integer, unknown | 10 |
| 3 | `hospital` | 医院 | demographics | string | free-text | 3 |
| 4 | `urban_residence` | 是否城市（1非城市2城市） | demographics | enum | `1`, `2`, unknown | 3 |
| 5 | `hypertension_history` | 高血压病史（有1，无0，不详unknown） | history | enum | `1`, `0`, unknown | 9 |
| 6 | `diabetes_history` | 糖尿病史（有1，无0，不详unknown） | history | enum | `1`, `0`, unknown | 9 |
| 7 | `hyperlipidemia_history` | 高血脂病史（有1，无0，不详unknown） | history | enum | `1`, `0`, unknown | 4 |
| 8 | `heart_disease_history` | 既往心脏疾病分组 | history | enum | `1`, `0`, unknown | 2 |
| 9 | `stroke_history` | 卒中分组（有1，无0，不详unknown） | history | enum | `1`, `0`, unknown | 2 |
| 10 | `tumor_history` | 既往肿瘤 | history | enum | `1`, `0`, unknown | **2** |
| 11 | `smoking_history` | 是否吸烟 | lifestyle | enum | `1`, `0`, unknown | 10 |
| 12 | `drinking_history` | 是否饮酒 | lifestyle | enum | `1`, `0`, unknown | 10 |
| 13 | `single_multiple` | 单发多发 | aneurysm | enum | `single`, `multiple`, unknown | **0** |
| 14 | `aneurysm_location` | 动脉瘤位置（1颈内，2中，3前，4后循环，unknown不详） | aneurysm | enum | `1`-`4`, unknown | **0** |
| 15 | `hh_grade` | HH分组 | score | enum | I-V, unknown | **0** |
| 16 | `wfns_grade` | WFNS分组 | score | enum | I-V, unknown | **0** |
| 17 | `fisher_grade` | Fisher分级 | score | enum | I-IV, unknown | **0** |
| 18 | `surgery_method` | 最终手术方式 | surgery | enum | code list, unknown | **0** |
| 19 | `onset_to_admission_time` | 出现症状到入院前时间 | timeline | duration | `≤24h`, `>24h`, unknown | **0** |
| 20 | `admission_to_surgery_time` | 手术距离入院时间 | timeline | duration | `≤72h`, `>72h`, unknown | **0** |
| 21 | `mrs_score` | mRS评分 | score | enum | 0-6, unknown | **0** |
| 22 | `in_hospital_death` | 在院死亡 | discharge | enum | `1`, `0`, unknown | **0** |
| 23 | `transfer` | 是否转诊 | discharge | enum | `1`, `0`, unknown | **0** |

(`gold_case_count` is the number of `mock_general` gold cases that include this field; not all 8 cases assert the same fields.)

## Coverage Gap Summary

Currently covered: **12 of 22 schema fields** (the 23rd export column maps to the same `aneurysm_location` field that the schema lists once).

Currently uncovered: **10 of 22 schema fields**, grouped by the kind of recall path each one exercises:

- **String free-text** _(closed by Phase A 2026-05-18)_: ~~`hospital`~~ ✅. Rule path matches `XX医院` substring patterns through `_extract_hospital`. Covered by `eval-mock-009` (`海安市第三人民医院`), `eval-mock-010` (`海安县中医院`), and `eval-mock-005` (unknown path).
- **Enum derived from address-or-residence** _(closed by Phase A 2026-05-18)_: ~~`urban_residence`~~ ✅. `pre_redaction_derivations` runs before PHI redaction. Covered by `eval-mock-009` (urban: `南京市鼓楼区五一路` → `2`), `eval-mock-010` (rural: `海安县曲塘镇五星村3组` → `1`), and `eval-mock-005` (no address → unknown). Privacy boundary pinned by `test_phase_a_address_redaction_holds_in_deidentified_ir`.
- **Negative-history binary** _(closed by Phase B 2026-05-20)_: ~~`tumor_history`~~ ✅. Same shape as existing diabetes/heart-disease tests. Covered by `eval-mock-011` (positive: `恶性肿瘤病史` → `1`) and `eval-mock-007` (implicit-negative: `既往史：无特殊` → `0`).
- **Imaging-fact enums**: `single_multiple`, `aneurysm_location`. Source sections are `辅助检查 / 影像报告 / CTA / DSA`. Fixtures need short imaging-report paragraphs with terms like `单发动脉瘤`, `右侧后交通动脉动脉瘤`, `多发动脉瘤`. The rule path is `_fact_then_code_evidence` plus `synonyms / code_map`.
- **Score grades**: `hh_grade`, `wfns_grade`, `fisher_grade`, `mrs_score`. Source sections are `入院记录 / 评分 / 体格检查`. Fixtures need lines like `Hunt-Hess II级`, `Fisher 3级`, `WFNS Ⅲ级`, `mRS 1分`. Most rule-only paths look for the synonym followed by a Roman/Arabic numeral; a fixture without an explicit grade must remain unknown to verify the path does not hallucinate.
- **Surgery method enum**: `surgery_method`. Source sections include `手术记录 / 出院诊断 / 医嘱`. Fixtures with `开颅夹闭术`, `介入栓塞`, `保守治疗` directly hit `code_map`.
- **Time-difference duration**: `onset_to_admission_time`, `admission_to_surgery_time`. `extract_mode: computed_from_facts` with explicit `pre_redaction_derivations` and dedicated logic in `_recorded_or_derived_score_evidence`. Fixtures need both clear ("发病3小时入院" / "入院后2天行手术") and edge-case (no time stated) variants.
- **Discharge outcome**: `in_hospital_death`, `transfer`. Source section `出院记录 / 病案首页`. Fixtures need `好转出院`, `院内死亡`, `转上级医院` variants.

## Phased Fixture Expansion Plan

The current 8-case set was chosen to exercise the rule paths actually used by demographics + history + lifestyle. Expanding it to all 22 fields needs to happen in phases that each carry a precision-task baseline regeneration; otherwise a single mega-batch would couple too many uncorrelated changes to one commit.

Each phase below is one PLAN task. Phases are ordered by the cost of authoring credible synthetic fixtures plus the risk of bugs they would expose.

### Completed Phases

#### Phase A — Demographics completion (done 2026-05-18)

Added: `hospital`, `urban_residence`. Rule-only baseline rose from 1.0 (54/54) to 1.0 (72/72). Two new fixtures (`eval-mock-009` urban + `eval-mock-010` rural) plus extended gold on `eval-mock-005` to anchor the unknown path. Privacy boundary pinned: `家庭住址` lines redact to `[REDACTED]`; only the safe `是否城市判定` derivation block carries into the de-identified DocumentIR. The LLM-assisted baseline temporarily dropped from 1.0 to 0.9722 (70/72) on two unrelated LLM gaps; the `eval-mock-003 / age` half closed on the same day via E1-005 `rule_pre_accepted`; the remaining `evidence_text` paraphrase gap closed on 2026-05-19 by E1-001 v3 prompt rewrite (LLM baseline now 1.0 (72/72) deterministically). Anchor: `docs/PLAN_HISTORY.md`, ROADMAP E1-010 Phase A.

#### Phase B — History completion (done 2026-05-20)

Added: `tumor_history`. Rule-only baseline rose from 1.0 (72/72) to 1.0 (80/80). One new fixture (`eval-mock-011` with explicit `恶性肿瘤病史` → positive) plus extended gold on `eval-mock-007` (`既往史：无特殊` implicit-negative → `tumor_history="0"`). LLM-assisted baseline also 1.0 (80/80). Token cost: 26,406 input / 7,946 output. Anchor: `PLAN.md` Done "PLAN-mock-general-phase-B", ROADMAP E1-010 Phase B.

### Active Phases

### Phase C — Imaging facts (aneurysm group)

Adds: `single_multiple`, `aneurysm_location`.

Rationale: `code_map`-driven enum. Needs imaging-report excerpts to look real. Two fixtures: one single-aneurysm at 颈内动脉, one multiple-aneurysm at posterior circulation. The 后循环 case is the harder one because it tests synonym mapping (`基底动脉`, `椎动脉`, `小脑后下动脉`, `PICA`, `SCA`, `PCA`) — likely to expose at least one recall gap.

### Phase D — Score grades

Adds: `hh_grade`, `wfns_grade`, `fisher_grade`, `mrs_score`.

Rationale: highest expected gap surface. The rule path is fragile around Roman / Arabic / 中文 numerals (`Ⅲ` vs `3` vs `三`) and around English-Chinese mixing (`Hunt-Hess` vs `HH` vs `亨特-赫斯`). Three fixtures: a clean `HH II级 / WFNS II级 / Fisher 3级 / mRS 1分` admission record, a numeral-style `Hunt-Hess Ⅲ级`, and a chart without explicit grades to validate unknown handling. This phase will likely lower the accuracy floor before raising it again.

### Phase E — Surgery method

Adds: `surgery_method`.

Rationale: directly `code_map`-mappable. Three fixtures covering 开颅夹闭, 介入栓塞, and 保守治疗 outcomes. Care needed: 开颅夹闭术 and 介入栓塞术 can co-occur for staged treatment; the gold should encode the canonical "final" decision per the schema label.

### Phase F — Timeline durations

Adds: `onset_to_admission_time`, `admission_to_surgery_time`.

Rationale: `computed_from_facts`. The rule path needs to find both anchors (onset event, admission timestamp; admission timestamp, surgery timestamp) in the same case. Two fixtures: a complete one (3-hour onset window, surgery on day 2), and an edge case where surgery did not happen.

### Phase G — Discharge outcome

Adds: `in_hospital_death`, `transfer`.

Rationale: short `出院记录` paragraphs. Two fixtures: 好转出院, 院内死亡 with cause. The transfer field has trickier negation (`否认转诊` vs `转上级医院`).

## Execution Rules

Each phase follows the precision-task lifecycle codified in `AGENTS.md` and the existing `mock_general` baseline ratchet:

1. Add fixtures and gold YAML.
2. Run `python scripts/bootstrap-eval-fixtures.py --profile-id mock_general` to confirm processing succeeds.
3. Run `python scripts/run-extraction-eval.py --profile-id mock_general` to read the new accuracy.
4. If new gaps appear, decide whether they are (a) truthful baseline state that should be pinned in `test_evidence_first_extraction.py` like `eval-mock-008`, or (b) actual rule bugs that must be fixed in the same phase.
5. Regenerate baseline JSON with `--baseline`.
6. Update `test_eval_fixtures.py` accuracy floor and the fixture-count assertion.
7. Update `docs/ROADMAP.md` Active Baselines row.
8. Commit with `Refs: PLAN-mock-general-phase-<letter>` and a one-line description in `PLAN.md` Done.

Phases must be done one at a time. Mixing phases would obscure which fixture is responsible for which baseline shift.

## Long-Horizon: Beyond Synthetic Fixtures

Synthetic fixtures verify that the rule paths exist and behave consistently. They cannot validate generalization to real scanned EMRs. Real validation lives behind:

- `medical_inpatient_zh` evaluation profile (extraction): currently empty `gold_cases`. Needs reviewed de-identified records to populate. Tracked as ROADMAP `E2-002`.
- `medical_inpatient_zh` OCR evaluation profile: currently `template: true`, blocked by the missing real-hardware corpus. Tracked as ROADMAP `E2-001`.

Until those land, `mock_general` is the strictest precision contract on the project. The phase plan above expands it from "demographics + history + lifestyle" to "every field on the export sheet" so the contract surfaces real-rule gaps in every clinical category, not just the easy ones.

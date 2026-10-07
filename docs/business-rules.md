# Business Rules

A plain-English reference for the credit-risk domain behind **Credit Copilot**: what each
business entity represents, how the compliance (risk-control) checks run, and the structure &
content of the risk-compliance documents — both the *policy corpus* the checks cite and the
*credit memo* the system generates.

> Language note: this document is English-first, with Chinese glosses (括注) for key credit
> terms on first mention. Entity names are always shown as `English Name (中文名)`.

Related: [README](../README.md) · [简体中文 README](../README.zh-CN.md)

---

## 1. Business entities (业务实体 / 数据模型)

The database is a star schema centered on a four-level **counterparty hierarchy (主体层级)**.
The top level is the **borrowing group (集团)** — a corporate group whose exposures are
consolidated for risk and limit purposes. Below it sit **borrowers (借款人 / obligor)**, then
**main facilities (主授信额度)**, then **sub-facilities (子额度)**.

```
dim_borrowing_group (集团 — risk-consolidation unit)
  └─ dim_borrower         (借款人 / obligor)
       └─ dim_main_facility    (主授信额度)
            └─ dim_sub_facility  (子额度 — LC / Guarantee / Cash / Term / Aval)

Supporting entities (not in the chain):
  fact_rating          ratings over time — polymorphic: points at group / borrower / facility
  dim_involved_party   related parties & guarantees — attached to a main facility
  map_carm_wren        cross-system master-data mapping (CARM ↔ WREN)
  fact_utilization     monthly exposure / utilization — attached to a main facility
```

### 1.1 `dim_borrowing_group` — 集团 (risk-consolidation unit)

The top-level counterparty: a corporate group whose exposures are merged for a single risk view.

| Field | Meaning |
|---|---|
| `group_id` | Primary key |
| `group_name_cn` / `group_name_en` | Bilingual name (reports render `English (中文)`) |
| `country` / `industry` | Group country (ISO α-2) and primary industry |
| `consolidated_exposure_limit` | Consolidated exposure limit (敞口限额), the ceiling for the whole group |
| `risk_consolidation` | `full` / `partial` / `none` — whether risk is consolidated |
| `status` | `active` |

**Relationship:** parent of `dim_borrower`.

### 1.2 `dim_borrower` — 借款人 / obligor

A single legal entity that borrows, belonging to a group.

| Field | Meaning |
|---|---|
| `borrower_id` | Primary key |
| `group_id` | FK → `dim_borrowing_group` |
| `borrower_name_cn` / `borrower_name_en` | Bilingual legal name (`core + suffix + legal form`) |
| `legal_type` | Legal form: `Co., Ltd.` / `LLC` / `PLC` / `Ltd.` |
| `internal_rating` | Latest internal-rating **snapshot**; full history lives in `fact_rating` |

**Relationship:** child of `dim_borrowing_group`; parent of `dim_main_facility`; also rated in
`fact_rating` (`entity_type = 'borrower'`).

### 1.3 `dim_main_facility` — 主授信额度

A credit facility (loan line) extended to one borrower.

| Field | Meaning |
|---|---|
| `main_facility_id` | Primary key |
| `borrower_id` | FK → `dim_borrower` |
| `facility_type` | `Revolving` / `Term` / `Trade` / `Bridge` |
| `purpose` | `Working Capital` / `M&A Financing` / `Project Finance` / `Trade Finance` / `Capital Expenditure` / `Refinancing` / `Backup Liquidity` |
| `committed_amount` | Committed (authorized) amount |
| `currency` | ISO 4217 (`USD` / `EUR` / `CNY` / `GBP` / `HKD`) |
| `maturity_date` | Maturity date |

**Relationship:** child of `dim_borrower`; parent of `dim_sub_facility`, `dim_involved_party`,
`fact_utilization`; also rated in `fact_rating` (`entity_type = 'facility'`).

### 1.4 `dim_sub_facility` — 子额度

A sub-line drawn under a main facility (letters of credit, guarantees, cash, term, aval).

| Field | Meaning |
|---|---|
| `sub_facility_id` | Primary key |
| `main_facility_id` | FK → `dim_main_facility` |
| `sub_type` | `LC` / `Guarantee` / `Cash` / `Term` / `Aval` |
| `limit_amount` | Sub-limit (10–50% of the main facility's committed amount) |
| `utilization_amount` | Utilized amount |

**Relationship:** child of `dim_main_facility` only. Sub-facilities are **not** rated in
`fact_rating` (ratings stop at the main-facility level).

### 1.5 `fact_rating` — 评级 (time dimension)

Ratings for a group, borrower, or facility, with a validity window.

| Field | Meaning |
|---|---|
| `entity_type` + `entity_id` | **Polymorphic** reference — together point at a `group` / `borrower` / `facility` (no real FK possible) |
| `agency` | `internal` / `S&P` / `Moody's` |
| `grade` | Letter ladder: `AAA, AA+, AA, AA-, A+, A, A-, BBB+, BBB, BBB-, BB+, BB, BB-, B+, B, B-, CCC+, CCC, CCC-, CC, C, D` |
| `outlook` | `Stable` / `Positive` / `Negative` / `Developing` |
| `valid_from` / `valid_to` | Validity window — **`valid_to IS NULL` means "currently effective"** |
| `rating_date` | Date the rating was assigned |
| `methodology` | Agency-dependent (e.g. `Internal PD-LGD Model`) |

Historical (closed) ratings carry a non-NULL `valid_to`; the current rating is the row with
`valid_to IS NULL`.

### 1.6 `dim_involved_party` — 相关方 (role bridge)

Parties related to a facility: the obligor itself, plus guarantors and banks.

| Field | Meaning |
|---|---|
| `main_facility_id` | FK → `dim_main_facility` |
| `role` | `borrower` / `guarantor` / `agent_bank` / `arranger` / `security_agent` |
| `party_name` | Party name |
| `ownership_pct` | Ownership % (only the guarantor has a value — 100.0) |
| `is_internal` | `TRUE` only for the guarantor (a group-related internal party) |

The **guarantor (担保人)** is always the borrower's group (100% ownership, internal); bank roles
are external parties.

### 1.7 `map_carm_wren` — 跨系统映射 (CARM ↔ WREN)

Reconciles the same counterparty across two master-data systems. CARM is this app's system of
record; WREN is the external/legacy system. This table models the real pain point of
cross-system master-data mapping (数据质量 / data-quality scenario).

| Field | Meaning |
|---|---|
| `carm_entity_type` + `carm_entity_id` | CARM side (`CARM-{G\|B\|F}-{id}`) |
| `wren_entity_type` + `wren_entity_id` | WREN side; **`NULL` = unmatched** |
| `mapping_status` | `matched` (~85%) / `partial` (~8%) / `unmatched` (~7%) |
| `confidence` | Match confidence (matched 0.95–1.00, partial 0.60–0.85) |
| `last_refresh` | Last refresh date |

### 1.8 `fact_utilization` — 敞口 / 利用率 (monthly time series)

One row per main facility per month — how much of the committed line is actually used.

| Field | Meaning |
|---|---|
| `main_facility_id` | FK → `dim_main_facility` |
| `as_of_date` | Month-end observation date |
| `outstanding_amount` | Amount outstanding |
| `utilized_amount` | Drawn / used portion |
| `undrawn_amount` | Remaining available (`committed − utilized`) |

> Note: in the synthetic seed data, `outstanding_amount` and `utilized_amount` hold the same
> value — the generator does not yet distinguish "outstanding principal" from "drawn amount".

---

## 2. Compliance process (合规过程)

Compliance is **deterministic** — no LLM is involved in the rule layer. A query flows through a
five-stage pipeline:

```
resolve_entity → collect_facts → build_compliance_flags → compose_report → validate_report
```

1. **resolve_entity** — extract a name from the query (bilingual heuristic), fuzzy-search
   borrowers and groups. 0 hits → "not found"; >1 → "ambiguous" (with candidates); exactly 1 → that
   entity.
2. **collect_facts** — fetch the overview, ratings, facilities, exposure, related parties, and
   policy search in parallel; any failure degrades to a `ToolResult.failure` (never crashes).
3. **build_compliance_flags** — run the five deterministic rules below.
4. **compose_report** — assemble the 7-chapter memo (chapters 1–6 deterministic, chapter 7 LLM).
5. **validate_report** — check the 7 chapters are present and citation coverage ≥ 0.9; on failure,
   re-compose up to 2 times, then append a `Validation Failed` section.

### 2.1 The five deterministic rules (五条确定性规则)

Each rule emits one `Flag` with `level` (`error` / `warning`), `rule` (title), `policy_ref`
(citation), and `detail` (message).

| level | rule | policy_ref | Trigger condition | Detail |
|---|---|---|---|---|
| warning | Real Estate Access Restriction | `industry-access-policy#Real Estate Access` | `industry == "Real Estate"` | "…is in the real estate industry; new credit must be approved by head office" |
| error | Rating Access Threshold | `rating-access-policy#Rating Threshold` | current internal rating ≤ `BB-` on the grade ladder | "Internal rating X ≤ BB-; new credit is prohibited" |
| warning | Negative Rating Outlook | `rating-access-policy#Outlook Management` | current rating `outlook == "Negative"` | "Outlook Negative; strengthen post-lending monitoring from quarterly to monthly" |
| error | Group Exposure Over Limit | `exposure-limits-and-concentration-policy#Single Group Limit` | exposure ratio `used / limit > 100%` | "Consolidated exposure X exceeds the limit Y (NNN.N%)" |
| warning | Concentration Warning | `exposure-limits-and-concentration-policy#Concentration Warning` | `80% ≤ used / limit ≤ 100%` | "Consolidated exposure utilization NNN.N% ≥ 80%" |

**How the rule inputs are derived:**

- **Industry** — from the overview row (`industry` or `group_industry`); exact, case-sensitive match
  against `"Real Estate"`.
- **Current internal rating** — among ratings with `valid_to IS NULL`, prefer `agency = 'internal'`
  (else the latest current row); the grade is compared against `"BB-"` using the `GRADES` ladder
  (unknown grades are treated as "at or below"). A `BB-` borrower with a `Negative` outlook emits
  **both** the rating and outlook flags.
- **Exposure ratio** — `get_exposure` sums `utilized_amount` across a group's facilities at the
  latest `as_of_date` and divides by `consolidated_exposure_limit`. The over-limit (error) and
  concentration (warning) checks are mutually exclusive (`elif`).

### 2.2 Where compliance flags surface

- **Chapter 6 `Policy & Compliance Check`** — one bullet per flag: `- [{level}] {rule}: {detail}`,
  with a `[p:{policy_ref}]` citation. If no flags fire: "No compliance restrictions triggered".
- **Chapter 7 `Risk Points & Conclusion`** — the flags are summarized into the conclusion.
- **`CreditMemo.compliance_flags`** — top-level list, e.g. `[error] Rating Access Threshold`.
- **`CreditMemo.data_gaps`** — always notes "no financial data" (the model has no financial
  statements); adds "policy search unavailable" if the RAG lookup failed.

---

## 3. Risk-compliance documents · the policy corpus (政策语料)

Four policy documents live in
[`apps/backend/docs/policy/`](../apps/backend/docs/policy/). They are chunked for RAG: each
`## ` heading becomes a chunk whose id is `title#heading` (where `title` is the filename with the
leading numeric prefix stripped, e.g. `03-rating-access-policy` → `rating-access-policy`). A
`policy_ref` such as `rating-access-policy#Rating Threshold` therefore resolves to a specific
document section.

> Status legend: ✅ = enforced by a code rule · ⬜ = documented in the corpus but not yet enforced.

### 3.1 [`01-industry-access-policy.md`](../apps/backend/docs/policy/01-industry-access-policy.md) — Industry Access Policy

| Section | Rule | Status |
|---|---|---|
| `Real Estate Access` | New real-estate credit needs head-office risk-committee approval; a real-estate group's consolidated exposure ≤ 70% of its limit; land-reserve / commercial-property project finance generally not granted | ✅ (only the "Real Estate" access flag) |
| `Restricted Industries` | Steel, cement, electrolytic aluminum, flat glass, etc. — maintain existing exposure only, no new exposure | ⬜ |
| `Technology Industry Support` | Semiconductors, data centers, software services — key-support list; exposure limits may be raised by 10% | ⬜ |

### 3.2 [`02-exposure-limits-and-concentration-policy.md`](../apps/backend/docs/policy/02-exposure-limits-and-concentration-policy.md) — Exposure Limits & Concentration

| Section | Rule | Status |
|---|---|---|
| `Single Group Limit` | A group's consolidated exposure must not exceed its approved limit; if exceeded, reduce or collateralize within 30 days | ✅ |
| `Concentration Warning` | 80% utilization → warning; 100% → new credit suspended | ✅ |
| `Single Borrower Limit` | A single borrower's exposure ≤ 15% of the bank's net tier-1 capital | ⬜ |

### 3.3 [`03-rating-access-policy.md`](../apps/backend/docs/policy/03-rating-access-policy.md) — Rating Access

| Section | Rule | Status |
|---|---|---|
| `Rating Threshold` | Internal rating BB- or below (BB-, B+, B, B-, CCC+, CCC, CCC-, CC, C, D) → new credit prohibited | ✅ |
| `Outlook Management` | Negative → strengthen monitoring quarterly→monthly; Developing → new credit suspended | ✅ (Negative) / ⬜ (Developing) |
| `External Rating Reference` | S&P / Moody's external rating >2 notches below internal → rating-difference review | ⬜ |

### 3.4 [`04-guarantee-policy.md`](../apps/backend/docs/policy/04-guarantee-policy.md) — Guarantee

| Section | Rule | Status |
|---|---|---|
| `Guarantor Eligibility` | Guarantor must be the group's parent or an equally qualified, already-credited entity; third-party guarantors need 2 years of audited financials + minimum capital | ⬜ |
| `Unsecured Exposure` | Unsecured trade finance posts ≥ 10% margin; total clean (unsecured) exposure ≤ 30% of group limit | ⬜ |

---

## 4. Risk-compliance documents · the generated report (生成报告)

The output is a `CreditMemo` with **7 chapters** (`SECTION_TITLES`):

| # | Chapter | Content source |
|---|---|---|
| 1 | Borrower & Group Overview | Deterministic |
| 2 | Ratings | Deterministic |
| 3 | Credit Facilities | Deterministic |
| 4 | Exposure & Limit Utilization | Deterministic |
| 5 | Related Parties & Guarantees | Deterministic |
| 6 | Policy & Compliance Check | Deterministic (the five rules) |
| 7 | Risk Points & Conclusion | LLM (degrades to a rule summary on failure) |

**Citations (可追溯性):** every claim is traceable to its source —
data citations `[t:table#id]` and policy citations `[p:policy_ref]`.

**Result validation:** the report must contain all 7 chapters and meet a citation-coverage
threshold (≥ 0.9 across citable chapters). If not, `run_report` re-composes (bounded, ≤ 2) and
otherwise appends a `Validation Failed` section — the API always returns a well-formed memo rather
than crashing.

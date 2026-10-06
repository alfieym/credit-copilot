"""Generate the Credit Copilot synthetic dataset (stdlib only, deterministic).

- Writes CSVs to ``data/seed/``; field names mirror ``src/credit_copilot/db/schema.sql``.
- All primary keys are generated explicitly here, so the seed never collides with DB sequences.
- Run: ``python data/generate_data.py``  (or ``make data``)

Design notes:
- Ratings use a letter scale (AAA..C) with an "internal" agency, to align with
  policy-doc wording such as "BB-rated borrowers". Real banks often use a 1-10
  numeric scale; a grade-band mapping table can be added later for domain modeling.
- ``map_carm_wren`` keeps ~7% unmatched records to demonstrate the real pain point
  of cross-system master-data mapping (data-quality scenario).
- Every counterparty is bilingual: ``name_cn`` + ``name_en`` so the report can
  present it as "English Name (中文名)".
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
OUT_DIR = Path(__file__).resolve().parent / "seed"
rng = random.Random(SEED)

TODAY = date(2026, 10, 5)

# --------------------------------------------------------------------------- #
# Base pools
# --------------------------------------------------------------------------- #
# Each group carries a bilingual brand stem (core_cn / core_en) and full names
# (name_cn / name_en), so every borrower inherits both a Chinese and an English name.
GROUPS = [
    {"name_cn": "恒远控股集团", "name_en": "Hengyuan Holdings Group",
     "core_cn": "恒远", "core_en": "Hengyuan", "country": "CN", "industry": "Automotive"},
    {"name_cn": "蓝峰实业集团", "name_en": "Lanfeng Industrial Group",
     "core_cn": "蓝峰", "core_en": "Lanfeng", "country": "CN", "industry": "Real Estate"},
    {"name_cn": "中科能源集团", "name_en": "Zhongke Energy Group",
     "core_cn": "中科", "core_en": "Zhongke", "country": "CN", "industry": "Energy"},
    {"name_cn": "天晟科技集团", "name_en": "Tiansheng Technology Group",
     "core_cn": "天晟", "core_en": "Tiansheng", "country": "CN", "industry": "Technology"},
    {"name_cn": "康泰医药集团", "name_en": "Kangtai Pharmaceutical Group",
     "core_cn": "康泰", "core_en": "Kangtai", "country": "CN", "industry": "Pharmaceuticals"},
    {"name_cn": "裕隆零售集团", "name_en": "Yulong Retail Group",
     "core_cn": "裕隆", "core_en": "Yulong", "country": "CN", "industry": "Retail"},
    {"name_cn": "宏基建工集团", "name_en": "Hongji Construction Group",
     "core_cn": "宏基", "core_en": "Hongji", "country": "CN", "industry": "Infrastructure"},
    {"name_cn": "汇通金融控股", "name_en": "Huitong Financial Holdings",
     "core_cn": "汇通", "core_en": "Huitong", "country": "CN", "industry": "Financial Services"},
    {"name_cn": "华宇电子集团", "name_en": "Huayu Electronics Group",
     "core_cn": "华宇", "core_en": "Huayu", "country": "CN", "industry": "Electronics"},
    {"name_cn": "盛达物流集团", "name_en": "Shengda Logistics Group",
     "core_cn": "盛达", "core_en": "Shengda", "country": "CN", "industry": "Logistics"},
    {"name_cn": "梅里迪安环球控股", "name_en": "Meridian Global Holdings",
     "core_cn": "梅里迪安", "core_en": "Meridian", "country": "HK", "industry": "Conglomerate"},
    {"name_cn": "阿特拉斯能源合伙", "name_en": "Atlas Energy Partners",
     "core_cn": "阿特拉斯", "core_en": "Atlas", "country": "US", "industry": "Energy"},
    {"name_cn": "奥利安消费集团", "name_en": "Orion Consumer Group",
     "core_cn": "奥利安", "core_en": "Orion", "country": "SG", "industry": "Retail"},
    {"name_cn": "维斯塔制药有限公司", "name_en": "Vesta Pharma Ltd",
     "core_cn": "维斯塔", "core_en": "Vesta", "country": "DE", "industry": "Pharmaceuticals"},
    {"name_cn": "凯斯特罗工业集团", "name_en": "Kestrel Industrials",
     "core_cn": "凯斯特罗", "core_en": "Kestrel", "country": "UK", "industry": "Manufacturing"},
]

# Business-descriptor suffixes, paired (cn, en) so each borrower gets a matched pair.
SUFFIXES = [
    ("汽车零部件", "Auto Parts"),
    ("动力总成", "Powertrain Systems"),
    ("新能源科技", "New Energy Technology"),
    ("装备制造", "Equipment Manufacturing"),
    ("供应链管理", "Supply Chain Management"),
    ("精工", "Precision Engineering"),
    ("商贸", "Trading"),
    ("置业开发", "Property Development"),
    ("置业投资", "Property Investment"),
    ("能源开发", "Energy Development"),
    ("清洁能源", "Clean Energy"),
    ("数据中心", "Data Center"),
    ("半导体", "Semiconductor"),
    ("软件服务", "Software Services"),
    ("生物制药", "Biopharmaceuticals"),
    ("医疗器械", "Medical Devices"),
    ("健康管理", "Health Management"),
    ("商业管理", "Business Management"),
    ("百货连锁", "Department Store Chain"),
    ("工程建设", "Engineering Construction"),
    ("市政工程", "Municipal Engineering"),
    ("投资管理", "Investment Management"),
    ("融资租赁", "Financial Leasing"),
    ("显示科技", "Display Technology"),
    ("精密电子", "Precision Electronics"),
    ("集成电路", "Integrated Circuits"),
    ("仓储物流", "Warehousing & Logistics"),
    ("国际货运", "International Freight"),
    ("食品贸易", "Food Trading"),
    ("工业制造", "Industrial Manufacturing"),
    ("机械", "Machinery"),
]

LEGAL_CN = ["有限责任公司", "股份有限公司", "有限公司"]
LEGAL_EN = ["Ltd.", "PLC", "LLC", "Co., Ltd."]

FACILITY_TYPES = ["Revolving", "Term", "Trade", "Bridge"]
FACILITY_PURPOSES = ["Working Capital", "M&A Financing", "Project Finance",
                     "Trade Finance", "Capital Expenditure", "Refinancing",
                     "Backup Liquidity"]
SUB_TYPES = ["LC", "Guarantee", "Cash", "Term", "Aval"]
CURRENCIES = ["USD", "EUR", "CNY", "GBP", "HKD"]

GRADES = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
          "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"]
GRADE_WEIGHTS = [0.3, 0.4, 0.6, 0.8, 1.2, 1.6, 2.0, 3.0, 4.5, 6.0,
                 6.0, 5.0, 4.0, 3.0, 2.0, 1.5, 0.8, 0.5, 0.3, 0.2, 0.1, 0.05]
OUTLOOKS = ["Stable", "Positive", "Negative", "Developing"]
OUTLOOK_WEIGHTS = [70, 12, 12, 6]

METHODOLOGY = {
    "internal": "Internal PD-LGD Model",
    "S&P": "S&P Global Rating Criteria",
    "Moody's": "Moody's Rating Methodology",
}

BANKS = ["Bank of China", "HSBC", "Citi", "Standard Chartered",
         "Deutsche Bank", "China Merchants Bank", "ICBC", "JPMorgan"]


def rnd_amount(lo_m: float, hi_m: float) -> float:
    """Return a deterministic random amount in the given millions range.

    Implementation: ``round(uniform(lo_m, hi_m) * 1_000_000, 2)`` — stored as a full
    value; the millions formatting happens at CSV write time.
    """
    return round(rng.uniform(lo_m, hi_m) * 1_000_000, 2)


# --------------------------------------------------------------------------- #
# Per-table generation
# --------------------------------------------------------------------------- #
def gen_groups() -> list[dict]:
    """Generate the 15 borrowing-group rows from the ``GROUPS`` pool.

    Implementation: enumerates ``GROUPS``, giving each a deterministic ``group_id``, a
    random consolidated exposure limit (500–5000m), a risk-consolidation mode, and
    bilingual names.
    """
    rows = []
    for i, g in enumerate(GROUPS, start=1):
        rows.append({
            "group_id": i,
            "group_name_cn": g["name_cn"],
            "group_name_en": g["name_en"],
            "parent_entity_id": None,           # reserved; NULL to avoid a cyclic FK with borrower
            "country": g["country"],
            "industry": g["industry"],
            "consolidated_exposure_limit": rnd_amount(500, 5000),
            "risk_consolidation": rng.choice(["full", "full", "partial", "none"]),
            "status": "active",
        })
    return rows


def gen_borrowers(groups: list[dict]) -> list[dict]:
    """Generate 2–6 borrowers per group with matched bilingual names.

    Implementation: for each group, sample a business suffix and legal form, then build
    ``name_cn = core_cn + suffix_cn + legal_cn`` and
    ``name_en = core_en + suffix_en + legal_en``; sequential ids start at 1001.
    """
    rows = []
    borrower_id = 1001
    for group_id, g in enumerate(groups, start=1):
        n = rng.randint(2, 6)
        for _ in range(n):
            suffix_cn, suffix_en = rng.choice(SUFFIXES)
            legal_cn = rng.choice(LEGAL_CN)
            legal_en = rng.choice(LEGAL_EN)
            rows.append({
                "borrower_id": borrower_id,
                "group_id": group_id,
                "borrower_name_cn": f"{g['core_cn']}{suffix_cn}{legal_cn}",
                "borrower_name_en": f"{g['core_en']} {suffix_en} {legal_en}",
                "country": g["country"],
                "industry": g["industry"],
                "legal_type": legal_en,
                "internal_rating": rng.choices(GRADES, weights=GRADE_WEIGHTS)[0],
                "status": "active",
            })
            borrower_id += 1
    return rows


def gen_main_facilities(borrowers: list[dict]) -> list[dict]:
    """Generate 1–3 main credit facilities per borrower.

    Implementation: each facility gets a type, currency, committed amount (10–800m), a
    maturity 1–7 years out, and a purpose; ids start at 2001.
    """
    rows = []
    fid = 2001
    for b in borrowers:
        n = rng.randint(1, 3)
        for _ in range(n):
            ftype = rng.choice(FACILITY_TYPES)
            rows.append({
                "main_facility_id": fid,
                "borrower_id": b["borrower_id"],
                "facility_name": f"{rng.choice(FACILITY_PURPOSES)} · {ftype}",
                "facility_type": ftype,
                "currency": rng.choice(CURRENCIES),
                "committed_amount": rnd_amount(10, 800),
                "maturity_date": TODAY + timedelta(days=365 * rng.randint(1, 7)),
                "purpose": rng.choice(FACILITY_PURPOSES),
                "status": "active",
            })
            fid += 1
    return rows


def gen_sub_facilities(mains: list[dict]) -> list[dict]:
    """Generate 0–3 sub-facilities per main facility.

    Implementation: each sub draws a type (LC / Guarantee / Cash / Term / Aval) and a
    limit of 10–50% of the main facility's committed amount, with utilization 10–90% of
    that limit; ids start at 3001.
    """
    rows = []
    sid = 3001
    for m in mains:
        n = rng.choices([0, 1, 2, 3], weights=[30, 40, 20, 10])[0]
        for _ in range(n):
            limit = round(m["committed_amount"] * rng.uniform(0.1, 0.5), 2)
            rows.append({
                "sub_facility_id": sid,
                "main_facility_id": m["main_facility_id"],
                "sub_type": rng.choice(SUB_TYPES),
                "currency": m["currency"],
                "limit_amount": limit,
                "utilization_amount": round(limit * rng.uniform(0.1, 0.9), 2),
                "maturity_date": m["maturity_date"],
                "status": "active",
            })
            sid += 1
    return rows


def _rating(rid: int, etype: str, eid: int, agency: str, grade: str | None = None,
            valid_from: date | None = None, valid_to: date | None = None) -> dict:
    """Build one rating row.

    Implementation: uses the explicit ``grade``/``valid_from``/``valid_to`` when given,
    otherwise samples a grade and a random date within the past ~400 days; outlook and
    methodology are derived from the agency.
    """
    g = grade or rng.choices(GRADES, weights=GRADE_WEIGHTS)[0]
    rd = valid_from or (TODAY - timedelta(days=rng.randint(30, 400)))
    return {
        "rating_id": rid,
        "entity_type": etype,
        "entity_id": eid,
        "agency": agency,
        "grade": g,
        "outlook": rng.choices(OUTLOOKS, weights=OUTLOOK_WEIGHTS)[0],
        "methodology": METHODOLOGY[agency],
        "valid_from": rd,
        "valid_to": valid_to,
        "rating_date": rd,
    }


def gen_ratings(groups: list[dict], borrowers: list[dict], mains: list[dict]) -> list[dict]:
    """Generate ratings for groups, borrowers, facilities, plus historical (closed) rows.

    Implementation: one internal rating per group and borrower (borrower grade from
    ``internal_rating``), an optional S&P/Moody's rating (40% chance), an optional
    facility rating (50% chance), then closed historical ratings for the first 15
    borrowers to populate the time dimension.
    """
    rows = []
    rid = 1
    for g in groups:
        rows.append(_rating(rid, "group", g["group_id"], "internal"))
        rid += 1
    for b in borrowers:
        rows.append(_rating(rid, "borrower", b["borrower_id"], "internal",
                            grade=b["internal_rating"]))
        rid += 1
        if rng.random() < 0.4:
            rows.append(_rating(rid, "borrower", b["borrower_id"], rng.choice(["S&P", "Moody's"])))
            rid += 1
    for m in mains:
        if rng.random() < 0.5:
            rows.append(_rating(rid, "facility", m["main_facility_id"], "internal"))
            rid += 1
    # Historical ratings (valid_to set) to reflect the time dimension
    for b in borrowers[:15]:
        vf = TODAY - timedelta(days=rng.randint(600, 1000))
        rows.append(_rating(rid, "borrower", b["borrower_id"], "internal",
                            valid_from=vf, valid_to=vf + timedelta(days=rng.randint(200, 400))))
        rid += 1
    return rows


def gen_involved_parties(mains: list[dict], borrower_by_id: dict,
                         group_en_by_borrower: dict) -> list[dict]:
    """Generate involved parties per main facility.

    Implementation: every facility gets a ``borrower`` row, plus 1–3 sampled roles — a
    guarantor (the borrower's group, 100% ownership, internal) or an agent bank /
    arranger / security agent (a sampled bank, external).
    """
    rows = []
    pid = 1
    for m in mains:
        b = borrower_by_id[m["borrower_id"]]
        rows.append({
            "involved_party_id": pid,
            "main_facility_id": m["main_facility_id"],
            "party_name": b["borrower_name_en"],
            "role": "borrower",
            "ownership_pct": None,
            "country": b["country"],
            "is_internal": "false",
        })
        pid += 1
        for r in rng.sample(["guarantor", "agent_bank", "arranger", "security_agent"],
                            k=rng.randint(1, 3)):
            if r == "guarantor":
                pname = group_en_by_borrower[b["borrower_id"]]
                own = 100.0
                isint = "true"
                country = b["country"]
            else:
                pname = rng.choice(BANKS)
                own = None
                isint = "false"
                country = rng.choice(["CN", "HK", "US", "GB", "DE", "SG"])
            rows.append({
                "involved_party_id": pid,
                "main_facility_id": m["main_facility_id"],
                "party_name": pname,
                "role": r,
                "ownership_pct": own,
                "country": country,
                "is_internal": isint,
            })
            pid += 1
    return rows


def gen_carm_wren(groups: list[dict], borrowers: list[dict], mains: list[dict]) -> list[dict]:
    """Generate the CARM↔WREN cross-system mapping rows.

    Implementation: for each group/borrower/facility, sample a status with weights
    matched 85% / partial 8% / unmatched 7%; matched rows get high confidence and a
    WREN id, partial rows a suffixed id and lower confidence, unmatched rows a NULL id.
    """
    rows = []
    mid = 1
    entities = ([(("group", g["group_id"])) for g in groups]
                + [("borrower", b["borrower_id"]) for b in borrowers]
                + [("facility", m["main_facility_id"]) for m in mains])
    for etype, eid in entities:
        status = rng.choices(["matched", "partial", "unmatched"], weights=[85, 8, 7])[0]
        carm_id = f"CARM-{etype[0].upper()}-{eid:06d}"
        if status == "matched":
            wren_id = f"WREN-{etype[0].upper()}-{eid:06d}"
            conf = round(rng.uniform(0.95, 1.0), 3)
        elif status == "partial":
            wren_id = f"WREN-{etype[0].upper()}-{eid:06d}-A"
            conf = round(rng.uniform(0.6, 0.85), 3)
        else:
            wren_id = None
            conf = None
        rows.append({
            "map_id": mid,
            "carm_entity_type": etype,
            "carm_entity_id": carm_id,
            "wren_entity_type": etype,
            "wren_entity_id": wren_id,
            "mapping_status": status,
            "confidence": conf,
            "last_refresh": TODAY - timedelta(days=rng.randint(1, 400)),
        })
        mid += 1
    return rows


def gen_utilization(mains: list[dict]) -> list[dict]:
    """Generate 12 monthly utilization points per facility.

    Implementation: starts from a base utilization (30–85% of committed) and drifts it
    ±3% per month, clamped to [0, committed], writing one ``fact_utilization`` row per
    month ending at ``TODAY``.
    """
    rows = []
    uid = 1
    for m in mains:
        committed = m["committed_amount"]
        base = committed * rng.uniform(0.3, 0.85)
        for k in range(11, -1, -1):
            drift = rng.uniform(-0.03, 0.03)
            utilized = max(0.0, round(base * (1 + (11 - k) * drift), 2))
            utilized = min(utilized, committed)
            rows.append({
                "utilization_id": uid,
                "main_facility_id": m["main_facility_id"],
                "as_of_date": TODAY - timedelta(days=30 * k),
                "outstanding_amount": utilized,
                "utilized_amount": utilized,
                "undrawn_amount": round(committed - utilized, 2),
            })
            uid += 1
    return rows


# --------------------------------------------------------------------------- #
# CSV writing
# --------------------------------------------------------------------------- #
def _fmt(v):
    """Format one CSV cell: None -> '', date -> ISO, float -> 2 decimals."""
    if v is None:
        return ""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:.2f}"
    return v


def _write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    """Write one table's rows to ``data/seed/<name>.csv``.

    Implementation: creates the directory, opens the file, writes a header via
    ``csv.DictWriter`` (extra keys ignored), formats each cell with ``_fmt``, and prints
    a row-count line.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(v) for k, v in r.items()})
    print(f"  ✓ {name:<24} {len(rows):>5} rows -> seed/{name}.csv")


def main() -> None:
    """Generate the full synthetic dataset and write the 8 CSVs.

    Implementation: generates groups → borrowers → main/sub facilities → ratings →
    involved parties → cross-system mapping → utilization (each dependent on the prior
    output), then writes each table to ``data/seed/`` in that order.
    """
    print(f"Generating synthetic dataset (seed={SEED})...")
    groups = gen_groups()
    borrowers = gen_borrowers(GROUPS)
    mains = gen_main_facilities(borrowers)
    subs = gen_sub_facilities(mains)
    ratings = gen_ratings(groups, borrowers, mains)
    groups_by_id = {g["group_id"]: g["group_name_en"] for g in groups}
    parties = gen_involved_parties(
        mains,
        {b["borrower_id"]: b for b in borrowers},
        {b["borrower_id"]: groups_by_id[b["group_id"]] for b in borrowers},
    )
    carm = gen_carm_wren(groups, borrowers, mains)
    util = gen_utilization(mains)

    tables: list[tuple[str, list[str], list[dict]]] = [
        ("dim_borrowing_group",
         ["group_id", "group_name_cn", "group_name_en", "parent_entity_id", "country",
          "industry", "consolidated_exposure_limit", "risk_consolidation", "status"], groups),
        ("dim_borrower",
         ["borrower_id", "group_id", "borrower_name_cn", "borrower_name_en", "country",
          "industry", "legal_type", "internal_rating", "status"], borrowers),
        ("dim_main_facility",
         ["main_facility_id", "borrower_id", "facility_name", "facility_type",
          "currency", "committed_amount", "maturity_date", "purpose", "status"], mains),
        ("dim_sub_facility",
         ["sub_facility_id", "main_facility_id", "sub_type", "currency",
          "limit_amount", "utilization_amount", "maturity_date", "status"], subs),
        ("fact_rating",
         ["rating_id", "entity_type", "entity_id", "agency", "grade", "outlook",
          "valid_from", "valid_to", "rating_date", "methodology"], ratings),
        ("dim_involved_party",
         ["involved_party_id", "main_facility_id", "party_name", "role",
          "ownership_pct", "country", "is_internal"], parties),
        ("map_carm_wren",
         ["map_id", "carm_entity_type", "carm_entity_id", "wren_entity_type",
          "wren_entity_id", "mapping_status", "confidence", "last_refresh"], carm),
        ("fact_utilization",
         ["utilization_id", "main_facility_id", "as_of_date", "outstanding_amount",
          "utilized_amount", "undrawn_amount"], util),
    ]

    for name, fields, rows in tables:
        _write_csv(name, fields, rows)

    print("Done.")


if __name__ == "__main__":
    main()

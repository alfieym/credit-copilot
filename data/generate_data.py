"""生成「信贷分析师 Copilot」合成数据集（仅标准库，确定性可复现）。

- 输出 CSV 到 data/seed/，字段名与 src/credit_copilot/db/schema.sql 一一对应。
- 所有主键由本脚本显式生成，避免与数据库自增序列冲突。
- 运行：python data/generate_data.py   （或 `make data`）

设计说明：
- 评级统一采用字母刻度（AAA..C），含 internal 机构，便于与政策文档中
  "BB 级借款人" 之类表述保持一致；真实银行内部评级常为 1-10 数字刻度，
  后续可加一张 grade-band 映射表来体现领域建模。
- map_carm_wren 里保留约 7% 未匹配记录，用于演示「跨系统主数据映射」
  这一真实痛点（数据质量场景）。
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
# 基础池
# --------------------------------------------------------------------------- #
GROUPS = [
    {"name": "恒远控股集团", "core": "恒远", "country": "CN", "industry": "汽车制造"},
    {"name": "蓝峰实业集团", "core": "蓝峰", "country": "CN", "industry": "房地产"},
    {"name": "中科能源集团", "core": "中科", "country": "CN", "industry": "能源"},
    {"name": "天晟科技集团", "core": "天晟", "country": "CN", "industry": "科技"},
    {"name": "康泰医药集团", "core": "康泰", "country": "CN", "industry": "医药"},
    {"name": "裕隆零售集团", "core": "裕隆", "country": "CN", "industry": "零售"},
    {"name": "宏基建工集团", "core": "宏基", "country": "CN", "industry": "基建"},
    {"name": "汇通金融控股", "core": "汇通", "country": "CN", "industry": "金融"},
    {"name": "华宇电子集团", "core": "华宇", "country": "CN", "industry": "电子"},
    {"name": "盛达物流集团", "core": "盛达", "country": "CN", "industry": "物流"},
    {"name": "Meridian Global Holdings", "core": "Meridian", "country": "HK", "industry": "综合"},
    {"name": "Atlas Energy Partners", "core": "Atlas", "country": "US", "industry": "能源"},
    {"name": "Orion Consumer Group", "core": "Orion", "country": "SG", "industry": "零售"},
    {"name": "Vesta Pharma Ltd", "core": "Vesta", "country": "DE", "industry": "医药"},
    {"name": "Kestrel Industrials", "core": "Kestrel", "country": "UK", "industry": "制造"},
]

CN_SUFFIXES = [
    "汽车零部件", "动力总成", "新能源科技", "装备制造", "供应链管理", "精工", "商贸",
    "置业开发", "置业投资", "能源开发", "清洁能源", "数据中心", "半导体", "软件服务",
    "生物制药", "医疗器械", "健康管理", "商业管理", "百货连锁", "工程建设", "市政工程",
    "投资管理", "融资租赁", "显示科技", "精密电子", "集成电路", "仓储物流", "国际货运",
    "食品贸易", "工业制造", "机械",
]
EN_SUFFIXES = [
    "Auto Parts", "Power Systems", "Consumer Goods", "Logistics", "Manufacturing",
    "Trading", "Investment", "Energy Solutions", "Biotech", "Real Estate", "Capital",
    "Industrial", "Semiconductor", "Retail", "Distribution",
]
LEGAL_CN = ["有限责任公司", "股份有限公司", "有限公司"]
LEGAL_EN = ["Ltd.", "PLC", "LLC", "Co., Ltd."]

FACILITY_TYPES = ["Revolving", "Term", "Trade", "Bridge"]
FACILITY_PURPOSES = ["营运资金", "并购融资", "项目融资", "贸易融资", "资本支出", "再融资",
                     "备用流动性"]
SUB_TYPES = ["LC", "Guarantee", "Cash", "Term", "Aval"]
CURRENCIES = ["USD", "EUR", "CNY", "GBP", "HKD"]

GRADES = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
          "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"]
GRADE_WEIGHTS = [0.3, 0.4, 0.6, 0.8, 1.2, 1.6, 2.0, 3.0, 4.5, 6.0,
                 6.0, 5.0, 4.0, 3.0, 2.0, 1.5, 0.8, 0.5, 0.3, 0.2, 0.1, 0.05]
OUTLOOKS = ["Stable", "Positive", "Negative", "Developing"]
OUTLOOK_WEIGHTS = [70, 12, 12, 6]

METHODOLOGY = {
    "internal": "PD-LGD 内部模型",
    "S&P": "S&P 全球评级准则",
    "Moody's": "Moody's 评级方法学",
}

BANKS = ["中国银行", "汇丰银行 HSBC", "花旗银行 Citi", "渣打银行 Standard Chartered",
         "德意志银行 Deutsche Bank", "招商银行", "工商银行", "摩根大通 JPMorgan"]


def is_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def rnd_amount(lo_m: float, hi_m: float) -> float:
    """以百万为量级返回实际金额（float，写 CSV 时统一格式化）。"""
    return round(rng.uniform(lo_m, hi_m) * 1_000_000, 2)


# --------------------------------------------------------------------------- #
# 各表生成
# --------------------------------------------------------------------------- #
def gen_groups() -> list[dict]:
    rows = []
    for i, g in enumerate(GROUPS, start=1):
        rows.append({
            "group_id": i,
            "group_name": g["name"],
            "parent_entity_id": None,           # 预留，置空以避免与 borrower 的循环外键
            "country": g["country"],
            "industry": g["industry"],
            "consolidated_exposure_limit": rnd_amount(500, 5000),
            "risk_consolidation": rng.choice(["full", "full", "partial", "none"]),
            "status": "active",
        })
    return rows


def gen_borrowers(groups: list[dict]) -> list[dict]:
    rows = []
    borrower_id = 1001
    for group_id, g in enumerate(groups, start=1):
        n = rng.randint(2, 6)
        cjk = is_cjk(g["core"])
        for _ in range(n):
            suffix = rng.choice(CN_SUFFIXES if cjk else EN_SUFFIXES)
            if cjk:
                name = f"{g['core']}{suffix}{rng.choice(LEGAL_CN)}"
            else:
                name = f"{g['core']} {suffix}"
                if rng.random() < 0.7:
                    name += f" {rng.choice(LEGAL_EN)}"
            rows.append({
                "borrower_id": borrower_id,
                "group_id": group_id,
                "borrower_name": name,
                "country": g["country"],
                "industry": g["industry"],
                "legal_type": rng.choice(LEGAL_CN if cjk else LEGAL_EN),
                "internal_rating": rng.choices(GRADES, weights=GRADE_WEIGHTS)[0],
                "status": "active",
            })
            borrower_id += 1
    return rows


def gen_main_facilities(borrowers: list[dict]) -> list[dict]:
    rows = []
    fid = 2001
    for b in borrowers:
        n = rng.randint(1, 3)
        cjk = is_cjk(b["borrower_name"])
        for _ in range(n):
            ftype = rng.choice(FACILITY_TYPES)
            rows.append({
                "main_facility_id": fid,
                "borrower_id": b["borrower_id"],
                "facility_name": f"{rng.choice(FACILITY_PURPOSES)} · {ftype}",
                "facility_type": ftype,
                "currency": rng.choice(
                    ["CNY", "CNY", "USD", "HKD"] if cjk else ["USD", "EUR", "USD", "HKD"]
                ),
                "committed_amount": rnd_amount(10, 800),
                "maturity_date": TODAY + timedelta(days=365 * rng.randint(1, 7)),
                "purpose": rng.choice(FACILITY_PURPOSES),
                "status": "active",
            })
            fid += 1
    return rows


def gen_sub_facilities(mains: list[dict]) -> list[dict]:
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
    # 历史评级（valid_to 非空），体现时间维
    for b in borrowers[:15]:
        vf = TODAY - timedelta(days=rng.randint(600, 1000))
        rows.append(_rating(rid, "borrower", b["borrower_id"], "internal",
                            valid_from=vf, valid_to=vf + timedelta(days=rng.randint(200, 400))))
        rid += 1
    return rows


def gen_involved_parties(mains: list[dict], borrower_by_id: dict,
                         group_by_borrower: dict) -> list[dict]:
    rows = []
    pid = 1
    for m in mains:
        b = borrower_by_id[m["borrower_id"]]
        rows.append({
            "involved_party_id": pid,
            "main_facility_id": m["main_facility_id"],
            "party_name": b["borrower_name"],
            "role": "borrower",
            "ownership_pct": None,
            "country": b["country"],
            "is_internal": "false",
        })
        pid += 1
        for r in rng.sample(["guarantor", "agent_bank", "arranger", "security_agent"],
                            k=rng.randint(1, 3)):
            if r == "guarantor":
                pname = group_by_borrower[b["borrower_id"]]
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
# 写 CSV
# --------------------------------------------------------------------------- #
def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:.2f}"
    return v


def _write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(v) for k, v in r.items()})
    print(f"  ✓ {name:<24} {len(rows):>5} 行 -> seed/{name}.csv")


def main() -> None:
    print(f"生成合成数据集（seed={SEED}）...")
    groups = gen_groups()
    borrowers = gen_borrowers(GROUPS)
    mains = gen_main_facilities(borrowers)
    subs = gen_sub_facilities(mains)
    ratings = gen_ratings(groups, borrowers, mains)
    parties = gen_involved_parties(
        mains,
        {b["borrower_id"]: b for b in borrowers},
        {b["borrower_id"]: next(g["group_name"] for g in groups if g["group_id"] == b["group_id"])
         for b in borrowers},
    )
    carm = gen_carm_wren(groups, borrowers, mains)
    util = gen_utilization(mains)

    tables: list[tuple[str, list[str], list[dict]]] = [
        ("dim_borrowing_group",
         ["group_id", "group_name", "parent_entity_id", "country", "industry",
          "consolidated_exposure_limit", "risk_consolidation", "status"], groups),
        ("dim_borrower",
         ["borrower_id", "group_id", "borrower_name", "country", "industry",
          "legal_type", "internal_rating", "status"], borrowers),
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

    print("完成。")


if __name__ == "__main__":
    main()

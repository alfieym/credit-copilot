"""把 data/seed/*.csv 灌入 Postgres（需先 `docker compose up -d postgres`）。

运行：python -m credit_copilot.db.seed   （或 `make seed`，会自动先 `make data`）
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from credit_copilot.config import get_settings

SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "seed"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# 表 -> (CSV 文件, 列顺序)。列顺序需与 schema.sql 一致。
TABLES: dict[str, tuple[str, list[str]]] = {
    "dim_borrowing_group": ("dim_borrowing_group.csv",
        ["group_id", "group_name", "parent_entity_id", "country", "industry",
         "consolidated_exposure_limit", "risk_consolidation", "status"]),
    "dim_borrower": ("dim_borrower.csv",
        ["borrower_id", "group_id", "borrower_name", "country", "industry",
         "legal_type", "internal_rating", "status"]),
    "dim_main_facility": ("dim_main_facility.csv",
        ["main_facility_id", "borrower_id", "facility_name", "facility_type",
         "currency", "committed_amount", "maturity_date", "purpose", "status"]),
    "dim_sub_facility": ("dim_sub_facility.csv",
        ["sub_facility_id", "main_facility_id", "sub_type", "currency",
         "limit_amount", "utilization_amount", "maturity_date", "status"]),
    "fact_rating": ("fact_rating.csv",
        ["rating_id", "entity_type", "entity_id", "agency", "grade", "outlook",
         "valid_from", "valid_to", "rating_date", "methodology"]),
    "dim_involved_party": ("dim_involved_party.csv",
        ["involved_party_id", "main_facility_id", "party_name", "role",
         "ownership_pct", "country", "is_internal"]),
    "map_carm_wren": ("map_carm_wren.csv",
        ["map_id", "carm_entity_type", "carm_entity_id", "wren_entity_type",
         "wren_entity_id", "mapping_status", "confidence", "last_refresh"]),
    "fact_utilization": ("fact_utilization.csv",
        ["utilization_id", "main_facility_id", "as_of_date", "outstanding_amount",
         "utilized_amount", "undrawn_amount"]),
}

# 清空顺序：先子后父，避免外键约束冲突
TRUNCATE_ORDER = [
    "fact_utilization", "dim_involved_party", "fact_rating", "map_carm_wren",
    "dim_sub_facility", "dim_main_facility", "dim_borrower", "dim_borrowing_group",
]


def main() -> None:
    cfg = get_settings()
    print(f"连接 Postgres: {cfg.postgres_host}:{cfg.postgres_port}/{cfg.postgres_db}")
    with psycopg.connect(cfg.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        cur.execute("TRUNCATE " + ", ".join(TRUNCATE_ORDER) + " CASCADE")
        for table, (csv_file, columns) in TABLES.items():
            path = SEED_DIR / csv_file
            if not path.exists():
                raise FileNotFoundError(f"缺少 {path}，请先运行 `make data` 生成")
            with path.open("r", encoding="utf-8") as f:
                with cur.copy(
                    f"COPY {table} ({', '.join(columns)}) FROM STDIN "
                    "WITH (FORMAT CSV, HEADER true)"
                ) as copy:
                    copy.write(f.read())
            print(f"  ✓ {table}: 已加载 {path.name}")
        conn.commit()
    print("灌库完成。")


if __name__ == "__main__":
    main()

-- ============================================================================
-- Credit Copilot · star-schema model for wholesale / corporate credit
--
-- Entity hierarchy: borrowing_group -> borrower -> main_facility -> sub_facility
-- Related entities: fact_rating (ratings, time dimension), dim_involved_party
--                   (related parties), map_carm_wren (cross-system mapping),
--                   fact_utilization (exposure / utilization, time dimension)
--
-- Every entity carries bilingual names (name_cn + name_en) so the report can
-- present each counterparty as "English Name (Chinese Name)".
--
-- All primary keys are generated explicitly by data/generate_data.py (deterministic),
-- so SERIAL is not used, avoiding conflicts with the COPY-based seed.
-- ============================================================================

-- Borrowing group (risk-consolidation unit)
CREATE TABLE IF NOT EXISTS dim_borrowing_group (
    group_id                    INTEGER PRIMARY KEY,
    group_name_cn               TEXT NOT NULL,
    group_name_en               TEXT NOT NULL,
    parent_entity_id            INTEGER,              -- borrower_id of the group's parent (reserved, NULL for now)
    country                     TEXT NOT NULL,
    industry                    TEXT NOT NULL,         -- group's primary industry
    consolidated_exposure_limit NUMERIC(18, 2),       -- consolidated exposure limit (local-currency equivalent)
    risk_consolidation          TEXT,                  -- full / partial / none
    status                      TEXT NOT NULL DEFAULT 'active'
);

-- Borrower / obligor
CREATE TABLE IF NOT EXISTS dim_borrower (
    borrower_id       INTEGER PRIMARY KEY,
    group_id          INTEGER REFERENCES dim_borrowing_group (group_id),
    borrower_name_cn  TEXT NOT NULL,
    borrower_name_en  TEXT NOT NULL,
    country           TEXT NOT NULL,
    industry          TEXT NOT NULL,
    legal_type        TEXT,                            -- legal form: Co., Ltd. / LLC / PLC ...
    internal_rating   TEXT,                            -- latest internal-rating snapshot (letter scale; history in fact_rating)
    status            TEXT NOT NULL DEFAULT 'active'
);

-- Main facility
CREATE TABLE IF NOT EXISTS dim_main_facility (
    main_facility_id INTEGER PRIMARY KEY,
    borrower_id      INTEGER NOT NULL REFERENCES dim_borrower (borrower_id),
    facility_name    TEXT NOT NULL,
    facility_type    TEXT NOT NULL,                    -- Revolving / Term / Trade / Bridge
    currency         TEXT NOT NULL,                    -- ISO 4217
    committed_amount NUMERIC(18, 2) NOT NULL,
    maturity_date    DATE,
    purpose          TEXT,
    status           TEXT NOT NULL DEFAULT 'active'
);

-- Sub facility (LC / guarantee / cash / term ...)
CREATE TABLE IF NOT EXISTS dim_sub_facility (
    sub_facility_id    INTEGER PRIMARY KEY,
    main_facility_id   INTEGER NOT NULL REFERENCES dim_main_facility (main_facility_id),
    sub_type           TEXT NOT NULL,                  -- LC / Guarantee / Cash / Term / Aval
    currency           TEXT NOT NULL,
    limit_amount       NUMERIC(18, 2) NOT NULL,
    utilization_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
    maturity_date      DATE,
    status             TEXT NOT NULL DEFAULT 'active'
);

-- Ratings (time dimension: valid_from / valid_to, NULL means currently effective)
-- entity_id is a polymorphic FK (group / borrower / facility); a real FK is not
-- possible, so queries must combine entity_type + entity_id.
CREATE TABLE IF NOT EXISTS fact_rating (
    rating_id   INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,                         -- group / borrower / facility
    entity_id   INTEGER NOT NULL,
    agency      TEXT NOT NULL,                         -- internal / S&P / Moody's
    grade       TEXT NOT NULL,                         -- AAA..C letter scale
    outlook     TEXT,                                  -- Stable / Positive / Negative / Developing
    methodology TEXT,
    valid_from  DATE NOT NULL,
    valid_to    DATE,                                  -- NULL = currently effective
    rating_date DATE NOT NULL
);

-- Related parties (role bridge)
CREATE TABLE IF NOT EXISTS dim_involved_party (
    involved_party_id INTEGER PRIMARY KEY,
    main_facility_id  INTEGER NOT NULL REFERENCES dim_main_facility (main_facility_id),
    party_name        TEXT NOT NULL,
    role              TEXT NOT NULL,                   -- borrower / guarantor / agent_bank / arranger / security_agent
    ownership_pct     NUMERIC(5, 2),
    country           TEXT,
    is_internal       BOOLEAN NOT NULL DEFAULT FALSE
);

-- Cross-system entity mapping (CARM <-> WREN)
CREATE TABLE IF NOT EXISTS map_carm_wren (
    map_id          INTEGER PRIMARY KEY,
    carm_entity_type TEXT NOT NULL,                    -- borrower / facility / group
    carm_entity_id  TEXT NOT NULL,
    wren_entity_type TEXT NOT NULL,
    wren_entity_id  TEXT,                              -- NULL = unmatched
    mapping_status  TEXT NOT NULL,                     -- matched / partial / unmatched
    confidence      NUMERIC(4, 3),
    last_refresh    DATE,
    UNIQUE (carm_entity_type, carm_entity_id)
);

-- Facility utilization / exposure (time dimension, monthly)
CREATE TABLE IF NOT EXISTS fact_utilization (
    utilization_id    INTEGER PRIMARY KEY,
    main_facility_id  INTEGER NOT NULL REFERENCES dim_main_facility (main_facility_id),
    as_of_date        DATE NOT NULL,
    outstanding_amount NUMERIC(18, 2),
    utilized_amount   NUMERIC(18, 2),
    undrawn_amount    NUMERIC(18, 2),
    UNIQUE (main_facility_id, as_of_date)
);

-- Common indexes
CREATE INDEX IF NOT EXISTS idx_borrower_group ON dim_borrower (group_id);
CREATE INDEX IF NOT EXISTS idx_main_facility_borrower ON dim_main_facility (borrower_id);
CREATE INDEX IF NOT EXISTS idx_sub_facility_main ON dim_sub_facility (main_facility_id);
CREATE INDEX IF NOT EXISTS idx_rating_entity ON fact_rating (entity_type, entity_id, valid_from);
CREATE INDEX IF NOT EXISTS idx_involved_party_facility ON dim_involved_party (main_facility_id);
CREATE INDEX IF NOT EXISTS idx_utilization_facility_date ON fact_utilization (main_facility_id, as_of_date);

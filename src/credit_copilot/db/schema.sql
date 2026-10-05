-- ============================================================================
-- 信贷分析师 Copilot · 结构化星型模型（对公/批发信贷域）
--
-- 实体层级：borrowing_group → borrower → main_facility → sub_facility
-- 关联实体：fact_rating（评级，时间维）、dim_involved_party（相关方）、
--           map_carm_wren（跨系统映射）、fact_utilization（敞口/使用，时间维）
--
-- 所有主键由 data/generate_data.py 显式生成（确定性），故不用 SERIAL，
-- 避免与 COPY 灌库时的自增序列冲突。
-- ============================================================================

-- 借款集团（风险合并单元）
CREATE TABLE IF NOT EXISTS dim_borrowing_group (
    group_id                    INTEGER PRIMARY KEY,
    group_name                  TEXT NOT NULL,
    parent_entity_id            INTEGER,              -- 集团母公司的 borrower_id（预留，暂置空）
    country                     TEXT NOT NULL,
    industry                    TEXT NOT NULL,         -- 集团主行业
    consolidated_exposure_limit NUMERIC(18, 2),       -- 合并敞口限额（本币等值）
    risk_consolidation          TEXT,                  -- 风险合并方式：full/partial/none
    status                      TEXT NOT NULL DEFAULT 'active'
);

-- 借款人 / 债务人
CREATE TABLE IF NOT EXISTS dim_borrower (
    borrower_id     INTEGER PRIMARY KEY,
    group_id        INTEGER REFERENCES dim_borrowing_group (group_id),
    borrower_name   TEXT NOT NULL,
    country         TEXT NOT NULL,
    industry        TEXT NOT NULL,
    legal_type      TEXT,                              -- 法律形式：有限公司/SPV/Ltd/PLC...
    internal_rating TEXT,                              -- 最新内部评级快照（字母刻度，历史在 fact_rating）
    status          TEXT NOT NULL DEFAULT 'active'
);

-- 主额度
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

-- 子额度（信用证 / 担保 / 现金 / 定期 ...）
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

-- 评级（时间维：valid_from / valid_to，NULL 表示当前有效）
-- entity_id 为多态外键（group/borrower/facility），无法建真实 FK，查询时需结合 entity_type
CREATE TABLE IF NOT EXISTS fact_rating (
    rating_id   INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,                         -- group / borrower / facility
    entity_id   INTEGER NOT NULL,
    agency      TEXT NOT NULL,                         -- internal / S&P / Moody's
    grade       TEXT NOT NULL,                         -- AAA..C 字母刻度
    outlook     TEXT,                                  -- Stable / Positive / Negative / Developing
    methodology TEXT,
    valid_from  DATE NOT NULL,
    valid_to    DATE,                                  -- NULL = 当前有效
    rating_date DATE NOT NULL
);

-- 相关方（角色桥接）
CREATE TABLE IF NOT EXISTS dim_involved_party (
    involved_party_id INTEGER PRIMARY KEY,
    main_facility_id  INTEGER NOT NULL REFERENCES dim_main_facility (main_facility_id),
    party_name        TEXT NOT NULL,
    role              TEXT NOT NULL,                   -- borrower/guarantor/agent_bank/arranger/security_agent
    ownership_pct     NUMERIC(5, 2),
    country           TEXT,
    is_internal       BOOLEAN NOT NULL DEFAULT FALSE
);

-- 跨系统实体映射（CARM ↔ WREN）
CREATE TABLE IF NOT EXISTS map_carm_wren (
    map_id          INTEGER PRIMARY KEY,
    carm_entity_type TEXT NOT NULL,                    -- borrower / facility / group
    carm_entity_id  TEXT NOT NULL,
    wren_entity_type TEXT NOT NULL,
    wren_entity_id  TEXT,                              -- NULL = 未匹配
    mapping_status  TEXT NOT NULL,                     -- matched / partial / unmatched
    confidence      NUMERIC(4, 3),
    last_refresh    DATE,
    UNIQUE (carm_entity_type, carm_entity_id)
);

-- 额度使用 / 敞口（时间维，月度）
CREATE TABLE IF NOT EXISTS fact_utilization (
    utilization_id    INTEGER PRIMARY KEY,
    main_facility_id  INTEGER NOT NULL REFERENCES dim_main_facility (main_facility_id),
    as_of_date        DATE NOT NULL,
    outstanding_amount NUMERIC(18, 2),
    utilized_amount   NUMERIC(18, 2),
    undrawn_amount    NUMERIC(18, 2),
    UNIQUE (main_facility_id, as_of_date)
);

-- 常用索引
CREATE INDEX IF NOT EXISTS idx_borrower_group ON dim_borrower (group_id);
CREATE INDEX IF NOT EXISTS idx_main_facility_borrower ON dim_main_facility (borrower_id);
CREATE INDEX IF NOT EXISTS idx_sub_facility_main ON dim_sub_facility (main_facility_id);
CREATE INDEX IF NOT EXISTS idx_rating_entity ON fact_rating (entity_type, entity_id, valid_from);
CREATE INDEX IF NOT EXISTS idx_involved_party_facility ON dim_involved_party (main_facility_id);
CREATE INDEX IF NOT EXISTS idx_utilization_facility_date ON fact_utilization (main_facility_id, as_of_date);

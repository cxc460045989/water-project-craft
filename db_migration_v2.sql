-- ============================================================
-- 数据库增量迁移 v2 — 水分测定仪主流程控制器支撑表
-- 在现有 data.db 基础上新增 3 张表，不破坏原有数据
-- ============================================================

-- 1. 测试过程会话表 — 记录每次测试运行的完整生命周期
CREATE TABLE IF NOT EXISTS test_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   INTEGER NOT NULL,             -- 关联 experiments.id
    session_no      TEXT NOT NULL,                 -- 会话编号 (YYYYMMDD_HHMMSS)
    status          TEXT DEFAULT 'pending',        -- pending/running/done/cancelled/error
    current_stage   TEXT DEFAULT 'idle',           -- 当前阶段标识
    current_mode    TEXT DEFAULT '',               -- 当前模式: 分析水/全水
    aw_completed    INTEGER DEFAULT 0,             -- 分析水是否完成 0/1
    tw_completed    INTEGER DEFAULT 0,             -- 全水是否完成 0/1
    recheck_enabled INTEGER DEFAULT 0,             -- 是否启用复检
    recheck_done    INTEGER DEFAULT 0,             -- 复检是否完成
    error_message   TEXT,                          -- 异常信息
    started_at      TEXT DEFAULT (datetime('now','localtime')),
    finished_at     TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

-- 2. 原始称重数据表 — 每次称重的原始天平读数永久保存（与校正后数据物理隔离）
CREATE TABLE IF NOT EXISTS raw_weigh_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,             -- 关联 test_sessions.id
    experiment_id   INTEGER NOT NULL,             -- 关联 experiments.id
    row_idx         INTEGER NOT NULL,             -- 样品行索引 (0-based)
    position        INTEGER NOT NULL,             -- 样品位号 (1-based)
    sample_name     TEXT DEFAULT '',              -- 样品名称
    mode            TEXT DEFAULT '',              -- 测试模式
    weigh_scene     TEXT DEFAULT '',              -- 称重场景: 复检/分析水首轮/恒重第N轮/全水首轮
    cycle_index     INTEGER DEFAULT 0,            -- 恒重循环轮次 (非恒重场景为0)
    raw_weight      REAL NOT NULL,                -- 原始天平读数 (g)
    corrected_weight REAL NOT NULL,               -- 校正后重量 = raw_weight + correct_diff (g)
    correct_diff    REAL DEFAULT 0.0,             -- 使用的校正差值
    is_stable       INTEGER DEFAULT 1,            -- 读数是否达到稳定
    weigh_timestamp TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (session_id) REFERENCES test_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_raw_weigh_session ON raw_weigh_data(session_id);
CREATE INDEX IF NOT EXISTS idx_raw_weigh_experiment ON raw_weigh_data(experiment_id);

-- 3. 过程事件日志表 — 记录流程中所有关键节点的时间戳和状态变化
CREATE TABLE IF NOT EXISTS process_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,
    experiment_id   INTEGER NOT NULL,
    stage           TEXT NOT NULL,                 -- 阶段: init/recheck/aw_heat/aw_weigh/aw_const/...
    mode            TEXT DEFAULT '',               -- 当前模式
    event_type      TEXT NOT NULL,                 -- 事件类型: stage_enter/stage_exit/error/retry/stop
    event_data      TEXT DEFAULT '{}',             -- JSON 附加数据
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (session_id) REFERENCES test_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_process_events_session ON process_events(session_id);

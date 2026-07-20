# -*- coding: utf-8 -*-
"""数据库工具 - 微机全自动水分测定仪
SQLite 封装，统一管理试验参数与测试数据持久化
"""

import sqlite3, os, sys

if getattr(sys, 'frozen', False):
    # 先找 exe 同级目录，再 fallback 到 _internal（兼容打包和手工放置两种场景）
    _exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    _exe_path = os.path.join(_exe_dir, "data.db")
    _int_path = os.path.join(sys._MEIPASS, "data.db")
    DB_PATH = _exe_path if os.path.exists(_exe_path) else _int_path
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")


def get_conn():
    """获取数据库连接（自动创建表）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn):
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS params (
            id INTEGER PRIMARY KEY CHECK(id=1),
            unit TEXT DEFAULT "",
            tech_0 TEXT, tech_1 TEXT, tech_2 TEXT,
            tech_3 TEXT, tech_4 TEXT, tech_5 TEXT,
            method TEXT DEFAULT "gb",
            weigh_mode INTEGER DEFAULT 0,
            aw_temp REAL DEFAULT 105, aw_time INTEGER DEFAULT 60,
            aw_const_check INTEGER DEFAULT 1, aw_prec REAL DEFAULT 0.0010,
            aw_interval INTEGER DEFAULT 5,
            aw_low REAL DEFAULT 0.9000, aw_high REAL DEFAULT 1.1000,
            aw_fan INTEGER DEFAULT 0, aw_corr REAL DEFAULT 0.00,
            tw_temp REAL DEFAULT 105, tw_time INTEGER DEFAULT 60,
            tw_const_check INTEGER DEFAULT 1, tw_prec REAL DEFAULT 0.0030,
            tw_interval INTEGER DEFAULT 5,
            tw_low REAL DEFAULT 9.0000, tw_high REAL DEFAULT 12.0000,
            tw_fan INTEGER DEFAULT 1, tw_corr REAL DEFAULT 0.00,
            beep INTEGER DEFAULT 1, retest INTEGER DEFAULT 0,
            autoclear INTEGER DEFAULT 0, sample_count INTEGER DEFAULT 24, hy_current TEXT DEFAULT "",
            boot_password TEXT DEFAULT "1234", user_password TEXT DEFAULT "1234", admin_password TEXT DEFAULT "1234"
        );
        INSERT OR IGNORE INTO params (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS samples (
            row_id INTEGER PRIMARY KEY,
            sample_no TEXT, name TEXT, mode TEXT,
            tare_weight REAL, sample_weight REAL,
            check_dry_weight REAL, dry_weight REAL,
            moisture REAL, avg_moisture REAL, precision_val REAL
        );

        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_no TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            tech TEXT,
            unit TEXT,
            method TEXT,
            weigh_mode INTEGER,
            aw_temp REAL, aw_time INTEGER, aw_const_check INTEGER, aw_prec REAL, aw_interval INTEGER,
            aw_low REAL, aw_high REAL, aw_fan INTEGER, aw_corr REAL,
            tw_temp REAL, tw_time INTEGER, tw_const_check INTEGER, tw_prec REAL, tw_interval INTEGER,
            tw_low REAL, tw_high REAL, tw_fan INTEGER, tw_corr REAL,
            beep INTEGER, retest INTEGER, autoclear INTEGER,
            status TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS experiment_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL,
            row_idx INTEGER NOT NULL,
            name TEXT, mode TEXT,
            tare_weight REAL, sample_weight REAL,
            check_dry_weight REAL, dry_weight REAL,
            moisture REAL, avg_moisture REAL, precision_val REAL,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS raw_data_backup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER,
            row_idx INTEGER,
            name TEXT,
            mode TEXT,
            phase TEXT,
            raw_weight REAL,
            mid_val INTEGER,
            dry_weight REAL,
            tare_weight REAL,
            tare_offset REAL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS experiment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            实验ID INTEGER NOT NULL,
            批次号 TEXT,
            试验日期 TEXT,
            坩埚位号 TEXT,
            样品名 TEXT,
            模式 TEXT,
            坩埚重 REAL,
            样重 REAL,
            检查性干燥重 REAL,
            干燥后重 REAL,
            原始检查性干燥重 REAL,
            原始干燥重 REAL,
            水分 REAL,
            平均水分 REAL,
            精密度 REAL,
            分析水温度 REAL,
            分析水时间 INTEGER,
            全水温度 REAL,
            全水时间 INTEGER,
            完成时间 TEXT DEFAULT (datetime('now','localtime')),
            测试单位 TEXT,
            化验员 TEXT,
            FOREIGN KEY (实验ID) REFERENCES experiments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS moisture_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL,
            row_idx INTEGER NOT NULL,
            name TEXT,
            mode TEXT,
            tare_weight REAL,
            sample_weight REAL,
            dry_weight REAL,
            moisture REAL,
            avg_moisture REAL,
            precision_val REAL,
            calculated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS method_presets (
            method TEXT PRIMARY KEY,
            aw_temp REAL, aw_time INTEGER,
            aw_const_check INTEGER, aw_prec REAL, aw_interval INTEGER,
            tw_temp REAL, tw_time INTEGER,
            tw_const_check INTEGER, tw_prec REAL, tw_interval INTEGER,
            weigh_mode INTEGER,
            aw_low REAL, aw_high REAL, tw_low REAL, tw_high REAL,
            aw_corr REAL, tw_corr REAL,
            aw_fan INTEGER, tw_fan INTEGER,
            retest INTEGER, autoclear INTEGER
        );
    """)

    # 兼容旧库新增字段
    try:
        cur.execute("ALTER TABLE params ADD COLUMN sample_count INTEGER DEFAULT 24")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    try:
        cur.execute("ALTER TABLE params ADD COLUMN com_port TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE params ADD COLUMN boot_password TEXT DEFAULT '1234'")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE params ADD COLUMN user_password TEXT DEFAULT '1234'")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE params ADD COLUMN admin_password TEXT DEFAULT '1234'")
    except sqlite3.OperationalError:
        pass
    # v2: 原始干燥重量列（不丢失校正前的原始数据）
    try:
        cur.execute("ALTER TABLE experiment_results ADD COLUMN 原始检查性干燥重 REAL")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE experiment_results ADD COLUMN 原始干燥重 REAL")
    except sqlite3.OperationalError:
        pass


# ========== 工厂默认值 ==========

FACTORY_DEFAULTS = {
    "gb": {
        "aw_temp": 105, "aw_time": 60, "aw_const_check": 1, "aw_prec": 0.0010, "aw_interval": 3,
        "tw_temp": 105, "tw_time": 60, "tw_const_check": 1, "tw_prec": 0.0010, "tw_interval": 3,
        "weigh_mode": 0,
        "aw_low": 0.9000, "aw_high": 1.1000, "tw_low": 9.0000, "tw_high": 12.0000,
        "aw_corr": 0.00, "tw_corr": 0.00,
        "aw_fan": 1,
        "tw_fan": 1,
        "retest": 0, "autoclear": 1,
    },
    "kf": {
        "aw_temp": 145, "aw_time": 10, "aw_const_check": 0, "aw_prec": 0.0010, "aw_interval": 3,
        "tw_temp": 145, "tw_time": 30, "tw_const_check": 0, "tw_prec": 0.0010, "tw_interval": 3,
        "weigh_mode": 0,
        "aw_low": 0.9000, "aw_high": 1.1000, "tw_low": 9.0000, "tw_high": 12.0000,
        "aw_corr": 0.00, "tw_corr": 0.00,
        "aw_fan": 1,
        "tw_fan": 1,
        "retest": 0, "autoclear": 1,
    },
    "custom": {
        "aw_temp": 105, "aw_time": 60, "aw_const_check": 1, "aw_prec": 0.0010, "aw_interval": 3,
        "tw_temp": 105, "tw_time": 60, "tw_const_check": 1, "tw_prec": 0.0010, "tw_interval": 3,
        "weigh_mode": 0,
        "aw_low": 0.9000, "aw_high": 1.1000, "tw_low": 9.0000, "tw_high": 12.0000,
        "aw_corr": 0.00, "tw_corr": 0.00,
        "aw_fan": 1,
        "tw_fan": 1,
        "retest": 0, "autoclear": 1,
    },
}

# ========== 方法参数持久化 ==========

def load_method_preset(method):
    """读取指定方法的保存参数，无记录返回 None"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM method_presets WHERE method=?", (method,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_method_preset(method, **kwargs):
    """保存指定方法的参数（INSERT OR REPLACE）"""
    conn = get_conn()
    cols = ["method"] + list(kwargs.keys())
    ph = ["?"] * len(cols)
    vals = [method] + list(kwargs.values())
    conn.execute(
        f"INSERT OR REPLACE INTO method_presets ({', '.join(cols)}) VALUES ({', '.join(ph)})",
        vals
    )
    conn.commit()
    conn.close()


# ========== 参数读写 ==========

def load_params():
    """读取全部试验参数，返回 dict"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM params WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}


def save_params(**kwargs):
    """更新指定参数，立即提交"""
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values())
    conn.execute(f"UPDATE params SET {sets} WHERE id=1", vals)
    conn.commit()
    conn.close()


# ========== 密码读写 ==========

def load_passwords():
    """返回 {'boot': str, 'user': str, 'admin': str}"""
    conn = get_conn()
    row = conn.execute(
        "SELECT boot_password, user_password, admin_password FROM params WHERE id=1"
    ).fetchone()
    conn.close()
    if row:
        return {"boot": row[0] or "1234", "user": row[1] or "1234", "admin": row[2] or "1234"}
    return {"boot": "1234", "user": "1234", "admin": "1234"}


def save_password(pwd_type, value):
    """保存指定类型密码: 'boot' | 'user' | 'admin'"""
    col_map = {"boot": "boot_password", "user": "user_password", "admin": "admin_password"}
    col = col_map.get(pwd_type)
    if not col:
        return
    conn = get_conn()
    conn.execute(f"UPDATE params SET {col}=? WHERE id=1", (value,))
    conn.commit()
    conn.close()


# ========== 化验员快捷接口 ==========

def load_techs():
    """返回化验员名字列表 [str,...]"""
    d = load_params()
    return [d.get(f"tech_{i}", "") or "" for i in range(6)]


def save_tech(idx, name):
    save_params(**{f"tech_{idx}": name})


# ========== 测试数据读写 ==========

def load_samples():
    """读取全部 23 行样本数据"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM samples ORDER BY row_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_sample(row_id, **kwargs):
    """保存或更新某行样本数据（先读后合并，避免 INSERT OR REPLACE 丢失列）"""
    conn = get_conn()
    existing = conn.execute("SELECT * FROM samples WHERE row_id=?", (row_id,)).fetchone()
    if existing:
        existing = dict(existing)
        existing.update(kwargs)
        merged = {k: v for k, v in existing.items() if k != "row_id" and v is not None}
        if not merged:
            conn.close()
            return
        sets = ", ".join(f"{k}=?" for k in merged.keys())
        vals = list(merged.values())
        conn.execute(
            f"UPDATE samples SET {sets} WHERE row_id=?", vals + [row_id]
        )
    else:
        cols = ", ".join(kwargs.keys())
        ph = ", ".join("?" for _ in kwargs)
        vals = list(kwargs.values())
        conn.execute(
            f"INSERT INTO samples (row_id, {cols}) VALUES (?, {ph})",
            [row_id] + vals
        )
    conn.commit()
    conn.close()
def save_all_samples(data_list):
    """批量保存全部样本（data_list: [{col:val,...},...]）"""
    conn = get_conn()
    conn.execute("DELETE FROM samples")
    for row_id, row in enumerate(data_list):
        if row:
            cols = ", ".join(row.keys())
            ph = ", ".join("?" for _ in row)
            vals = list(row.values())
            conn.execute(
                f"INSERT INTO samples (row_id, {cols}) VALUES (?, {ph})",
                [row_id] + vals
            )
    conn.commit()
    conn.close()


def clear_sample_row(row_idx):
    """清除指定行的称量数据（坩埚重 + 样品重）

    row_idx: 0-based table row 索引（第0行=校正坩埚, 第1行=1号样品...）
    同时清除 experiment_samples 和 samples 两张表的数据。
    """
    conn = get_conn()
    # 清除 experiment_samples 表
    eid = get_latest_experiment_id()
    conn.execute(
        "UPDATE experiment_samples SET tare_weight=NULL, sample_weight=NULL "
        "WHERE experiment_id=? AND row_idx=?",
        (eid, row_idx)
    )
    # 清除 samples 表 (row_id = row_idx + 1, 因为 samples.row_id 从1开始)
    conn.execute(
        "UPDATE samples SET tare_weight=NULL, sample_weight=NULL WHERE row_id=?",
        (row_idx + 1,)
    )
    conn.commit()
    conn.close()


# ========== 调试入口 ==========
if __name__ == "__main__":
    # 测试
    conn = get_conn()
    print("数据库初始化完成:", DB_PATH)
    print("参数:", dict(conn.execute("SELECT * FROM params WHERE id=1").fetchone()))
    conn.close()



# ========== 实验记录读写 ==========

def create_experiment(batch_no="", tech="", unit="", method="gb", weigh_mode=0):
    """创建新实验记录，返回自增id"""
    import datetime
    params = load_params()
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO experiments (
            batch_no, tech, unit, method, weigh_mode,
            aw_temp, aw_time, aw_const_check, aw_prec, aw_interval,
            aw_low, aw_high, aw_fan, aw_corr,
            tw_temp, tw_time, tw_const_check, tw_prec, tw_interval,
            tw_low, tw_high, tw_fan, tw_corr,
            beep, retest, autoclear
        ) VALUES (?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,  ?,?,?)
    """, (
        batch_no or datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
        tech or params.get("hy_current", ""),
        unit or params.get("unit", ""),
        method or params.get("method", "gb"),
        weigh_mode if weigh_mode is not None else params.get("weigh_mode", 0),
        params.get("aw_temp", 105), params.get("aw_time", 60), params.get("aw_const_check", 1), params.get("aw_prec", 0.001), params.get("aw_interval", 5),
        params.get("aw_low", 0.9), params.get("aw_high", 1.1), params.get("aw_fan", 0), params.get("aw_corr", 0),
        params.get("tw_temp", 105), params.get("tw_time", 60), params.get("tw_const_check", 1), params.get("tw_prec", 0.003), params.get("tw_interval", 5),
        params.get("tw_low", 9.0), params.get("tw_high", 12.0), params.get("tw_fan", 1), params.get("tw_corr", 0),
        params.get("beep", 1), params.get("retest", 0), params.get("autoclear", 0),
    ))
    conn.commit()
    exp_id = cur.lastrowid
    conn.close()
    return exp_id


def save_experiment_samples(experiment_id, sample_list):
    """保存实验样品数据，先删后插
    sample_list: [{row_idx, name, mode, tare_weight, sample_weight, ...}]
    """
    conn = get_conn()
    conn.execute("DELETE FROM experiment_samples WHERE experiment_id=?", (experiment_id,))
    for s in sample_list:
        conn.execute("""
            INSERT INTO experiment_samples
                (experiment_id, row_idx, name, mode, tare_weight, sample_weight,
                 check_dry_weight, dry_weight, moisture, avg_moisture, precision_val)
            VALUES (?,?,?,?,?,?,  ?,?,?,?,?)
        """, (
            experiment_id,
            s.get("row_idx"),
            s.get("name", ""),
            s.get("mode", ""),
            s.get("tare_weight"),
            s.get("sample_weight"),
            s.get("check_dry_weight"),
            s.get("dry_weight"),
            s.get("moisture"),
            s.get("avg_moisture"),
            s.get("precision_val"),
        ))
    conn.commit()
    conn.close()


def load_experiment(experiment_id):
    """加载实验记录 + 样品列表"""
    conn = get_conn()
    exp = conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
    samples = conn.execute(
        "SELECT * FROM experiment_samples WHERE experiment_id=? ORDER BY row_idx",
        (experiment_id,)
    ).fetchall()
    conn.close()
    return dict(exp) if exp else None, [dict(s) for s in samples]


def load_experiment_list(limit=50):
    """加载最近实验列表"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, batch_no, created_at, tech, status FROM experiments ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_experiment_status(experiment_id, status):
    """更新实验状态: pending / weighing / testing / done / cancelled"""
    conn = get_conn()
    conn.execute("UPDATE experiments SET status=? WHERE id=?", (status, experiment_id))
    conn.commit()
    conn.close()


# ========== 实验样品实时读写（替代旧 samples 表） ==========

def get_latest_experiment_id():
    """获取最新实验ID，没有则创建"""
    conn = get_conn()
    row = conn.execute("SELECT id FROM experiments ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        eid = row[0]
    else:
        cur = conn.execute("INSERT INTO experiments (batch_no) VALUES ('')")
        eid = cur.lastrowid
    conn.close()
    return eid


def ensure_experiment():
    """确保有实验记录，返回 experiment_id"""
    return get_latest_experiment_id()


def upsert_experiment_sample(experiment_id, row_idx, **kwargs):
    """插入或更新某行样品数据（实时写入用）
    如果 row_idx 已存在则 UPDATE，否则 INSERT
    kwargs: name, mode, tare_weight, sample_weight, ...
    """
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM experiment_samples WHERE experiment_id=? AND row_idx=?",
        (experiment_id, row_idx)
    ).fetchone()
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [experiment_id, row_idx]
        conn.execute(
            f"UPDATE experiment_samples SET {sets} WHERE experiment_id=? AND row_idx=?",
            vals
        )
    else:
        cols = ", ".join(["experiment_id", "row_idx"] + list(kwargs.keys()))
        ph = ", ".join(["?"] * (len(kwargs) + 2))
        vals = [experiment_id, row_idx] + list(kwargs.values())
        conn.execute(
            f"INSERT INTO experiment_samples ({cols}) VALUES ({ph})",
            vals
        )
    conn.commit()
    conn.close()


def load_experiment_samples(experiment_id):
    """加载某实验的全部样品（按 row_idx 排序）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM experiment_samples WHERE experiment_id=? ORDER BY row_idx",
        (experiment_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_latest_samples():
    """加载最新实验的全部样品数据"""
    eid = get_latest_experiment_id()
    return load_experiment_samples(eid)


def batch_set_mode(mode):
    """批量更新所有样品的模式列（单条 SQL，不用逐行写）"""
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE experiment_samples SET mode=? WHERE mode IS NOT NULL AND mode != ''", (mode,))
        c.execute("UPDATE samples SET mode=? WHERE mode IS NOT NULL AND mode != ''", (mode,))
        conn.commit()
    except Exception as e:
        logger.error("[DB] batch_set_mode error: %s" % e)
    finally:
        conn.close()


# ========== 实验最终结果读写（仅完整完成流程后写入）==========

def save_experiment_result(实验ID, 批次号, 试验日期, 坩埚位号,
                           样品名, 模式, 坩埚重, 样重,
                           检查性干燥重, 干燥后重, 水分,
                           平均水分, 精密度,
                           分析水温度=None, 分析水时间=None, 全水温度=None, 全水时间=None,
                           测试单位="", 化验员=""):
    """写入一条最终实验结果"""
    conn = get_conn()
    conn.execute("""
        INSERT INTO experiment_results
            (实验ID, 批次号, 试验日期, 坩埚位号, 样品名, 模式,
             坩埚重, 样重, 检查性干燥重, 干燥后重,
             水分, 平均水分, 精密度,
             分析水温度, 分析水时间, 全水温度, 全水时间, 测试单位, 化验员)
        VALUES (?,?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?, ?,?)
    """, (实验ID, 批次号, 试验日期, 坩埚位号, 样品名, 模式,
          坩埚重, 样重, 检查性干燥重, 干燥后重,
          水分, 平均水分, 精密度,
          分析水温度, 分析水时间, 全水温度, 全水时间, 测试单位, 化验员))
    conn.commit()
    conn.close()


def save_experiment_results_batch(results_list):
    """批量写入最终实验结果 — 键号=(实验ID, 坩埚位号)唯一

    首次 INSERT 时记录批次号和试验日期作为键号;
    后续 UPDATE 时只更新结果数据, 保留首次键号不覆盖。
    """
    if not results_list:
        return
    conn = get_conn()
    for r in results_list:
        eid = r.get("实验ID")
        pos = r.get("坩埚位号")
        # 检查是否已存在同键号记录
        existing = conn.execute(
            "SELECT id FROM experiment_results WHERE 实验ID=? AND 坩埚位号=?",
            (eid, pos)
        ).fetchone()
        if existing:
            # 覆盖已有记录 — 保留首次键号(批次号/试验日期), 只更新结果数据
            conn.execute("""
                UPDATE experiment_results SET
                    样品名=?, 模式=?,
                    坩埚重=?, 样重=?, 检查性干燥重=?, 干燥后重=?,
                    原始检查性干燥重=?, 原始干燥重=?,
                    水分=?, 平均水分=?, 精密度=?,
                    分析水温度=?, 分析水时间=?, 全水温度=?, 全水时间=?,
                    测试单位=?, 化验员=?,
                    完成时间=datetime('now','localtime')
                WHERE id=?
            """, (
                r.get("样品名"), r.get("模式"),
                r.get("坩埚重"), r.get("样重"),
                r.get("检查性干燥重"), r.get("干燥后重"),
                r.get("原始检查性干燥重"), r.get("原始干燥重"),
                r.get("水分"), r.get("平均水分"), r.get("精密度"),
                r.get("分析水温度"), r.get("分析水时间"),
                r.get("全水温度"), r.get("全水时间"),
                r.get("测试单位"), r.get("化验员"),
                existing[0],
            ))
        else:
            conn.execute("""
                INSERT INTO experiment_results
                    (实验ID, 批次号, 试验日期, 坩埚位号, 样品名, 模式,
                     坩埚重, 样重, 检查性干燥重, 干燥后重,
                     原始检查性干燥重, 原始干燥重,
                     水分, 平均水分, 精密度,
                     分析水温度, 分析水时间, 全水温度, 全水时间, 测试单位, 化验员)
                VALUES (?,?,?,?,?,?, ?,?,?,?, ?,?, ?,?,?, ?,?,?,?, ?,?)
            """, (
                eid, r.get("批次号"), r.get("试验日期"),
                pos, r.get("样品名"), r.get("模式"),
                r.get("坩埚重"), r.get("样重"),
                r.get("检查性干燥重"), r.get("干燥后重"),
                r.get("原始检查性干燥重"), r.get("原始干燥重"),
                r.get("水分"), r.get("平均水分"), r.get("精密度"),
                r.get("分析水温度"), r.get("分析水时间"),
                r.get("全水温度"), r.get("全水时间"),
                r.get("测试单位"), r.get("化验员"),
            ))
    conn.commit()
    conn.close()


def query_experiment_results(start_date=None, end_date=None,
                              name_filter=None, limit=200):
    """查询最终实验结果
    参数:
        start_date: 'YYYY-MM-DD' 起始
        end_date:   'YYYY-MM-DD' 结束
        name_filter: 样品名称模糊匹配
        limit: 最大返回行数
    返回: list of dict
    """
    conn = get_conn()
    sql = "SELECT * FROM experiment_results WHERE 1=1"
    params = []
    if start_date:
        sql += ' AND "试验日期" >= ?'
        params.append(start_date)
    if end_date:
        sql += ' AND "试验日期" <= ?'
        params.append(end_date)
    if name_filter:
        sql += ' AND LOWER("样品名") LIKE LOWER(?)'
        params.append("%" + name_filter + "%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_experiment_result(result_id):
    """删除单条实验结果"""
    conn = get_conn()
    conn.execute("DELETE FROM experiment_results WHERE id=?", (result_id,))
    conn.commit()
    conn.close()


def delete_experiment_results_by_experiment(experiment_id):
    """删除某实验的全部结果"""
    conn = get_conn()
    conn.execute("DELETE FROM experiment_results WHERE experiment_id=?", (experiment_id,))
    conn.commit()
    conn.close()

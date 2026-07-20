# -*- coding: utf-8 -*-
"""Mock 数据种子脚本 — 一键准备完整测试数据

用法:
    python seed_mock_data.py

生成数据:
  - params: 标准试验参数（样品数 24, 分析水105℃/60min, 全水105℃/60min）
  - experiment_samples: 校正坩埚 + 6个分析水 + 4个全水样品
  - experiments: 一个实验记录

注意:
  - 坩埚重需与 Mock 仪器模拟器生成的值匹配（~18.5 + pos*0.25）
  - 样品重需在 Mock 称重范围内（分析水 0.9~1.1g, 全水 9~12g）
  - 运行后重启 App 即可看到完整数据
"""

import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "water_data.db")


def seed():
    # 先初始化表结构
    from db import _init_db
    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)
    conn.close()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ===== 1. params: 标准试验参数 =====
    conn.executescript("""
        INSERT OR REPLACE INTO params (id, unit, sample_count,
            aw_temp, aw_time, aw_prec, aw_interval, aw_fan, aw_corr,
            aw_const_check, aw_low, aw_high,
            tw_temp, tw_time, tw_prec, tw_interval, tw_fan, tw_corr,
            tw_const_check, tw_low, tw_high,
            beep, retest, autoclear, hy_current)
        VALUES (1, '测试单位', 24,
            105, 60, 0.0010, 5, 0, 0.50,
            1, 0.9000, 1.1000,
            105, 60, 0.0030, 5, 1, 0.50,
            1, 9.0000, 12.0000,
            0, 0, 0, '张三');
    """)

    # ===== 2. experiments =====
    conn.execute("DELETE FROM experiments")
    cur = conn.execute("INSERT INTO experiments (batch_no, tech, unit, status) VALUES (?,?,?,?)",
                       ("MOCK-20260719", "张三", "测试单位", "pending"))
    exp_id = cur.lastrowid

    # ===== 3. experiment_samples =====
    conn.execute("DELETE FROM experiment_samples WHERE experiment_id=?", (exp_id,))

    samples = [
        # row_idx, name,              mode,     tare_weight, sample_weight
        (0,  "校正坩埚",              "",       18.7500,     0.0),         # Mock pos=1: crucible 18.75
        (1,  "煤样-A1",              "分析水",  19.0000,     1.0004),      # Mock pos=2: crucible 19.0, sample ~1.0
        (2,  "煤样-A2",              "分析水",  19.2500,     0.9850),      # Mock pos=3
        (3,  "煤样-A3",              "分析水",  19.5000,     1.0120),      # Mock pos=4
        (4,  "煤样-A4",              "分析水",  19.7500,     0.9680),      # Mock pos=5
        (5,  "煤样-A5",              "分析水",  20.0000,     1.0450),      # Mock pos=6
        (6,  "煤样-A6",              "分析水",  20.2500,     0.9920),      # Mock pos=7
        (7,  "煤样-T1",              "全水",    20.5000,     10.0234),     # Mock pos=8: sample ~9.5+
        (8,  "煤样-T2",              "全水",    20.7500,     9.8760),      # Mock pos=9
        (9,  "煤样-T3",              "全水",    21.0000,     10.5120),     # Mock pos=10
        (10, "煤样-T4",              "全水",    21.2500,     9.6500),      # Mock pos=11
        # rows 11-23: 空行（样品名留空）
    ]

    # 补齐空行到 24 行
    for r in range(11, 24):
        samples.append((r, "", "", None, None))

    for row_idx, name, mode, tare, sw in samples:
        conn.execute("""
            INSERT INTO experiment_samples
                (experiment_id, row_idx, name, mode, tare_weight, sample_weight)
            VALUES (?,?,?,?,?,?)
        """, (exp_id, row_idx, name, mode, tare, sw))

    # ===== 4. samples 表（兼容） =====
    conn.execute("DELETE FROM samples")
    for row_idx, name, mode, tare, sw in samples:
        conn.execute("""
            INSERT INTO samples (row_id, name, mode, tare_weight, sample_weight)
            VALUES (?,?,?,?,?)
        """, (row_idx + 1, name, mode, tare, sw))

    conn.commit()
    conn.close()

    print("=" * 60)
    print("Mock 数据种子完成!")
    print(f"  实验ID: {exp_id}")
    print(f"  样品: 校正坩埚 + 6个分析水 + 4个全水 + 13个空行 = 24行")
    print()
    print("启动方式:")
    print("  set WATER_MODE=mock")
    print("  set WATER_SPEED_MODE=1")
    print("  python main_app.py")
    print()
    print("全流程测试步骤:")
    print("  1. 启动 App → 表格应显示 10 个样品 + 校正坩埚")
    print("  2. 批量称重: 选中行 -> 称量称重 -> 验证坩埚重/样品重")
    print("  3. 开始测试 -> 观察升温->恒温->称重(校正坩埚先)->恒重->计算")
    print("  4. 追加样品: 点击追加 → 新增行 → 称量")
    print("  5. 切换模式: 双击模式列 -> 分析水/全水")
    print("=" * 60)


if __name__ == "__main__":
    seed()

# -*- coding: utf-8 -*-
"""Mock 模式下测试完整「开始测试」流程

用法:
    python test_controller_mock.py

先决条件:
    - 需先运行一次称样流程（seed 脚本），确保 experiment_samples 表中有样品数据
    - 或运行: python test_controller_mock.py --seed  自动填充 Mock 样品数据

流程:
    1. 启动 Mock 仪器模拟器（温度、天平自动生成上行帧）
    2. 创建 DeviceOperator + TestProcessController
    3. 调用 controller.start()
    4. 全程通过信号监听输出进度
    5. 验证: 初始化 → 复检称重 → 分析水(加热/称重/恒重/计算) → 全水(加热/称重/恒重/计算) → 完成
"""

import sys, os, time

os.environ['WATER_SPEED_MODE'] = '1'  # 加速模式: 升温极快


def seed_mock_samples():
    """向数据库填充 Mock 样品数据（模拟已完成的称样流程）"""
    from db import get_conn, ensure_experiment, save_params
    import datetime

    # 1. 设置试验参数
    save_params(
        aw_temp=105, aw_time=1,      # 加速: 1分钟
        aw_const_check=1, aw_prec=0.0010, aw_interval=1,
        aw_fan=0, aw_corr=0.50,
        tw_temp=105, tw_time=1,
        tw_const_check=1, tw_prec=0.0030, tw_interval=1,
        tw_fan=1, tw_corr=0.50,
        retest=1,                     # 启用复检
        beep=1,
        hy_current="测试员",
        unit="鹤壁市淇天仪器",
    )
    print("[SEED] 参数已设置")

    # 2. 创建实验 + 样品数据（模拟称样完成）
    eid = ensure_experiment()
    conn = get_conn()

    # 清空旧数据
    conn.execute("DELETE FROM experiment_samples WHERE experiment_id=?", (eid,))
    # 确保 experiment_results 表列正确（中文列名可能因旧迁移缺失）
    conn.execute("DROP TABLE IF EXISTS experiment_results")
    conn.execute("""
        CREATE TABLE experiment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            "实验ID" INTEGER NOT NULL,
            "批次号" TEXT,
            "试验日期" TEXT,
            "坩埚位号" TEXT,
            "样品名" TEXT,
            "模式" TEXT,
            "坩埚重" REAL,
            "样重" REAL,
            "检查性干燥重" REAL,
            "干燥后重" REAL,
            "水分" REAL,
            "平均水分" REAL,
            "精密度" REAL,
            "分析水温度" REAL,
            "分析水时间" INTEGER,
            "全水温度" REAL,
            "全水时间" INTEGER,
            "完成时间" TEXT DEFAULT (datetime('now','localtime')),
            "测试单位" TEXT,
            "化验员" TEXT
        )
    """)

    samples = [
        # row_idx, name, mode, tare, sample
        (0, "校正坩埚", "分析水", 18.5000, 18.5000),
        (1, "1号样", "分析水", 19.1234, 1.0012),
        (2, "2号样", "分析水", 19.2345, 0.9987),
        (3, "3号样", "分析水", 19.3456, 1.0034),
        (4, "4号样", "全水",   19.4567, 10.1234),
        (5, "5号样", "全水",   19.5678, 10.0567),
        (6, "6号样", "全水",   19.6789, 9.9876),
    ]

    for row_idx, name, mode, tare, sample in samples:
        conn.execute("""
            INSERT OR REPLACE INTO experiment_samples
                (experiment_id, row_idx, name, mode, tare_weight, sample_weight)
            VALUES (?,?,?,?,?,?)
        """, (eid, row_idx, name, mode, tare, sample))
        # 同时写入 samples 表（兼容旧接口）
        conn.execute("""
            INSERT OR REPLACE INTO samples
                (row_id, name, mode, tare_weight, sample_weight)
            VALUES (?,?,?,?,?)
        """, (row_idx + 1, name, mode, tare, sample))

    conn.commit()
    conn.close()
    print("[SEED] 已填充 %d 个样品 (3分析水 + 3全水)" % len(samples))
    print("[SEED] experiment_id=%d" % eid)

    # 更新实验状态
    from db import update_experiment_status
    update_experiment_status(eid, "weighing")  # 标记为称量完成，等待测试
    return eid


def run_test():
    """执行完整端到端 Mock 测试"""
    print("=" * 60)
    print("  微机全自动水分测定仪 — Mock 全流程测试")
    print("=" * 60)

    # ---- 阶段1: 启动 Mock 仪器 ----
    print("\n[1/4] 启动 Mock 仪器模拟器...")
    from mock_instrument import MockInstrumentSimulator, SimSerialAdapter
    from serial_comm import SerialManager

    sim = MockInstrumentSimulator()
    sim.set_online(True)
    sim.start()

    mgr = SerialManager(parent=None)
    mgr._serial = SimSerialAdapter(sim, serial_mgr=mgr)
    mgr._config.port = "MOCK"

    # 不需要 poll timer: send_cmd_with_uplink_check 自行读取上行帧
    # 加 poll timer 会与 send_cmd_with_uplink_check 竞争读帧，导致命令发送无限重试
    print("   Mock 仪器已启动: 在线, 25°C, 天平0g")

    # ---- 阶段2: 创建控制器 ----
    print("\n[2/4] 创建主流程控制器...")
    from PySide2.QtCore import QCoreApplication, QTimer
    app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication(sys.argv)

    from core_data_entities import DeviceOperator
    from test_process_controller import TestProcessController

    device_op = DeviceOperator(mgr)
    controller = TestProcessController(device_op)

    # 结果收集
    result_holder = {"done": False, "error": None, "data": None}

    # ---- 阶段3: 连接信号 ----
    print("\n[3/4] 连接标准化信号...")

    _STAGE_CN = {
        "init": "初始化", "recheck": "复检称重",
        "aw_heat": "分析水-升温", "aw_weigh": "分析水-称重",
        "aw_const": "分析水-恒重", "aw_calc": "分析水-计算",
        "tw_heat": "全水-升温", "tw_weigh": "全水-称重",
        "tw_const": "全水-恒重", "tw_calc": "全水-计算",
        "finishing": "收尾", "done": "完成", "error": "异常",
    }

    def on_stage_changed(stage, idx, total, mode):
        cn = _STAGE_CN.get(stage, stage)
        print("  [STAGE] %-12s  %d/%d  mode=%s" % (cn, idx + 1, total, mode))

    def on_process_update(data):
        desc = data.get("stage_desc", "")
        if desc:
            print("     %s" % desc)

    def on_temp_progress(data):
        stage = data.get("stage", "?")
        temp = data.get("current_temp", 0)
        target = data.get("target_temp", 0)
        remaining = data.get("remaining_sec", 0)
        print("     [温区] %s 当前%.1f℃ 目标%d℃ 剩余%.0fs" %
              (stage, temp, target, remaining))

    def on_weigh_progress(data):
        print("     [称重] 位号%d 读数%.4fg 场景:%s" %
              (data.get("position", 0), data.get("weight", 0),
               data.get("scene", "")))

    def on_cycle_progress(data):
        print("     [恒重] 第%d/%d轮 diff=%.6fg 阈值=%.4fg" %
              (data.get("cycle_index", 0) + 1, data.get("max_cycles", 0),
               data.get("weight_diff", 0), data.get("precision", 0)))

    def on_test_finished(data):
        print("\n" + "=" * 60)
        print("  ★ 测试完成!")
        print("=" * 60)
        aw = data.get("aw_results", {})
        tw = data.get("tw_results", {})
        if aw:
            print("  分析水: 平均水分=%.4f%%  精密度=%.4f  samples=%d" %
                  (aw.get("avg_moisture", 0), aw.get("precision", 0),
                   aw.get("sample_count", 0)))
        if tw:
            print("  全水:   平均水分=%.4f%%  精密度=%.4f  samples=%d" %
                  (tw.get("avg_moisture", 0), tw.get("precision", 0),
                   tw.get("sample_count", 0)))
        print("=" * 60)
        result_holder["done"] = True
        result_holder["data"] = data
        app.quit()

    def on_test_error(msg):
        print("\n  ✗ 测试异常: %s" % msg)
        result_holder["error"] = msg
        result_holder["done"] = True
        app.quit()

    def on_test_stopped():
        print("\n  ■ 测试已手动停止")
        result_holder["done"] = True
        app.quit()

    controller.stage_changed.connect(on_stage_changed)
    controller.process_update.connect(on_process_update)
    controller.sub_temp_progress.connect(on_temp_progress)
    controller.sub_weigh_progress.connect(on_weigh_progress)
    controller.sub_cycle_progress.connect(on_cycle_progress)
    controller.test_finished.connect(on_test_finished)
    controller.test_error.connect(on_test_error)
    controller.test_stopped.connect(on_test_stopped)

    # ---- 阶段4: 启动测试 ----
    print("\n[4/4] 启动测试流程...\n")
    print("-" * 60)

    # 延迟 100ms 启动（让事件循环就绪）
    QTimer.singleShot(100, controller.start)

    # 安全超时: 300秒后强制退出（加速模式下全流程约2-3分钟）
    QTimer.singleShot(300000, lambda: (
        print("\n[超时] 300秒未完成, 强制退出"),
        controller.stop(),
        app.quit()
    ))

    # 进入事件循环
    app.exec_()

    # ---- 输出结果 ----
    if result_holder["error"]:
        print("\n[结果] 测试异常: %s" % result_holder["error"])
        return 1
    elif result_holder["done"]:
        print("\n[结果] 测试通过 OK")
        return 0
    else:
        print("\n[结果] 测试未完成")
        return 1


# ================================================================
# 主入口
# ================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mock 模式下测试完整开始测试流程")
    parser.add_argument("--seed", action="store_true", help="先填充 Mock 样品数据再测试")
    args = parser.parse_args()

    if args.seed:
        print("[SEED] 正在填充 Mock 样品数据...")
        seed_mock_samples()
        print("[SEED] 完成。请再次运行 python test_controller_mock.py 开始测试\n")
        sys.exit(0)

    # 检查是否有样品数据
    try:
        from db import load_latest_samples
        samples = load_latest_samples()
        if not samples:
            print("[ERROR] 数据库中无样品数据!")
            print("  请先运行: python test_controller_mock.py --seed")
            sys.exit(1)
        valid = []
        for s in samples:
            name = s.get("name")
            sw = s.get("sample_weight")
            if name and (isinstance(name, str) and name.strip()) and sw is not None:
                valid.append(s)
        if not valid:
            print("[ERROR] 数据库中无有效样品数据 (need name + sample_weight)!")
            print("  请先运行: python test_controller_mock.py --seed")
            sys.exit(1)
        print("[INFO] 发现 %d 个有效样品" % len(valid))
    except Exception as e:
        import traceback
        print("[ERROR] 数据库检查失败: %s" % e)
        traceback.print_exc()
        print("  请先运行: python test_controller_mock.py --seed")
        sys.exit(1)

    sys.exit(run_test())

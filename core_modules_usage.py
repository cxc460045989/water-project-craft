# -*- coding: utf-8 -*-
"""核心底层能力模块 — 调用示例与参数说明
微机全自动水分测定仪 3个核心模块的使用示范

本文件为示例代码，演示3个模块的标准调用方式、信号连接、参数传递。
所有模块均为 QObject，可通过 moveToThread 放入工作线程运行。
"""

# ================================================================
# 前置准备: 创建设备操作接口
# ================================================================

# 假设已有已连接的 SerialManager 实例
# from serial_comm import SerialManager
# serial_mgr = SerialManager()
# serial_mgr.open("COM3", 9600)

# 创建设备操作封装（所有模块共享同一个实例）
# from core_data_entities import DeviceOperator
# device_op = DeviceOperator(serial_mgr)


# ================================================================
# 模块1: 批量称重模块 调用示例
# ================================================================
"""
BatchWeighModule — 所有称重场景复用

参数说明:
  - scene:        称重场景标记(str)，仅用于数据打标与进度展示
                  例: "分析水称重", "全水称重", "恒重第2轮称重"
  - positions:    样品位号列表(List[int])，1-based
                  例: [1, 2, 3, 4, 5]
  - correct_diff: 校正坩埚差值(float, g)
                  校正后重量 = 原始重量 + 校正坩埚差值
                  公式: correct_diff = 校正坩埚重 - 校正坩埚干燥重

信号:
  weigh_progress(dict):  称重进度
    {"step":int, "total":int, "position":int, "scene":str, "weight":float}
  weigh_finished(object): 称重完成，携带 BatchWeighResult
    result.scene          - 称重场景
    result.raw_weights    - 原始重量列表 (List[float])
    result.corrected_weights - 校正后重量列表 (List[float])
    result.records        - 详细记录 List[WeighRecord]
      record.position     - 样品位号
      record.raw_weight   - 原始读数
      record.corrected_weight - 校正后读数
      record.timestamp    - 时间戳
  weigh_error(str):      异常信息
"""


def example_batch_weigh(device_op):
    """模块1调用示例"""
    from batch_weigh_module import BatchWeighModule

    # 创建模块实例（全局唯一，所有称重场景复用）
    weigh_module = BatchWeighModule(device_op)

    # 连接信号
    def on_weigh_progress(data: dict):
        print("称重进度: 第%d/%d步 位号%d 读数%.4fg 场景:%s" % (
            data["step"], data["total"], data["position"],
            data["weight"], data["scene"]
        ))

    def on_weigh_finished(result):
        print("称重完成: 场景=%s 样品数=%d" % (result.scene, len(result.records)))
        for r in result.records:
            print("  位号%d: 原始=%.4fg  校正后=%.4fg" %
                  (r.position, r.raw_weight, r.corrected_weight))

    def on_weigh_error(msg: str):
        print("称重异常: %s" % msg)

    weigh_module.weigh_progress.connect(on_weigh_progress)
    weigh_module.weigh_finished.connect(on_weigh_finished)
    weigh_module.weigh_error.connect(on_weigh_error)

    # 启动称重
    weigh_module.start_weigh(
        scene="分析水称重",        # 称重场景标记
        positions=[1, 2, 3, 4],    # 样品位号 (1-based)
        correct_diff=0.5000,        # 校正坩埚差值
    )

    # 停止称重（任意时刻可调用）
    # weigh_module.stop()

    # 重置模块
    # weigh_module.reset()

    return weigh_module


# ================================================================
# 模块2: 控温恒温模块 调用示例
# ================================================================
"""
TempControlModule — 所有加热场景复用

参数说明:
  - target_temp:       目标设定温度(int, ℃)
                       例: 105(分析水), 105(全水)
  - constant_duration: 恒温总时长(int, 秒)
                       例: 3600(1小时), 600(10分钟)
  - blower_enable:     是否开启鼓风(bool)
                       与氮气互斥，鼓风优先
                       例: True(全水开鼓风), False(分析水不开鼓风)
  - nitrogen_enable:   是否开启氮气(bool)
                       鼓风关闭时生效
                       例: True(分析水开氮气)

信号:
  temp_progress(dict): 温区进度
    {"stage":"heating"/"holding", "current_temp":float,
     "target_temp":int, "remaining_sec":float, "percent":float}
  temp_finished():     恒温完成
  temp_error(str):     异常信息
"""


def example_temp_control(device_op):
    """模块2调用示例: 分析水模式（不鼓风，开氮气）"""
    from temp_control_module import TempControlModule

    temp_module = TempControlModule(device_op)

    def on_temp_progress(data: dict):
        stage_cn = "升温" if data["stage"] == "heating" else "恒温"
        print("%s阶段: 当前%.1f℃ 目标%d℃ 剩余%.0fs 完成%.1f%%" % (
            stage_cn, data["current_temp"], data["target_temp"],
            data["remaining_sec"], data["percent"]
        ))

    def on_temp_finished():
        print("恒温完成！")

    def on_temp_error(msg: str):
        print("控温异常: %s" % msg)

    temp_module.temp_progress.connect(on_temp_progress)
    temp_module.temp_finished.connect(on_temp_finished)
    temp_module.temp_error.connect(on_temp_error)

    # 分析水: 105℃, 1小时, 不开鼓风, 开氮气
    temp_module.start_heating(
        target_temp=105,
        constant_duration=3600,
        blower_enable=False,
        nitrogen_enable=True,
    )

    # 全水模式（开鼓风）调用:
    # temp_module.start_heating(
    #     target_temp=105,
    #     constant_duration=3600,
    #     blower_enable=True,
    #     nitrogen_enable=False,
    # )

    # 停止加热
    # temp_module.stop()

    return temp_module


def example_temp_control_tw(device_op):
    """模块2调用示例: 全水模式（开鼓风）"""
    from temp_control_module import TempControlModule

    temp_module = TempControlModule(device_op)

    temp_module.temp_progress.connect(lambda d: print(
        "全水温区: %s %.1f℃ → %d℃ 剩余%.0fs" %
        (d["stage"], d["current_temp"], d["target_temp"], d["remaining_sec"])
    ))
    temp_module.temp_finished.connect(lambda: print("全水恒温完成"))

    # 全水: 105℃, 1小时, 开鼓风
    temp_module.start_heating(
        target_temp=105,
        constant_duration=3600,
        blower_enable=True,
        nitrogen_enable=False,
    )
    return temp_module


# ================================================================
# 模块3: 恒重循环模块 调用示例
# ================================================================
"""
ConstantWeightCycleModule — 所有恒重场景复用

参数说明:
  - temp_config (TempControlConfig): 温度与气路配置
    .target_temp:        目标温度(℃)
    .constant_duration:  恒温时长(秒) — 此处不使用，见 interval_duration
    .blower_enable:      是否鼓风
    .nitrogen_enable:    是否氮气
  - interval_duration:   恒重称量间隔时长(int, 秒)
                         每轮循环的恒温时间，透传给控温恒温模块的 constant_duration
  - constant_precision:  恒重精度阈值(float, g)
                         判定条件: check_dry_weight - dry_weight <= precision
  - max_cycle_times:     最大循环次数(int)
                         防止无限循环，例: 3
  - correct_diff:        坩埚校正差值(float, g)
                         透传给称重模块
  - init_check_weight:   首轮检查性干燥重量(float, g)
                         第一轮循环的 check_dry_weight
  - positions:           称重样品位号列表(List[int])
  - weigh_scene:         称重场景标记(str)

信号:
  cycle_progress(dict):  循环进度
    {"cycle_index":int, "max_cycles":int, "weight_diff":float,
     "precision":float, "check_dry_weight":float, "dry_weight":float}
  cycle_finished(object): 恒重完成，携带 ConstantWeightResult
    result.final_dry_weight    - 最终干燥重量
    result.total_cycles        - 实际循环次数
    result.cycle_records       - 每轮称重记录 List[CycleRecord]
    result.is_precision_met    - 是否精度达标
    result.is_max_cycle_reached - 是否因最大次数终止
  cycle_error(str):      异常
  temp_progress(dict):   透传控温模块进度
  weigh_progress(dict):  透传称重模块进度
"""


def example_constant_weight(device_op):
    """模块3调用示例: 分析水恒重循环"""
    from constant_weight_module import ConstantWeightCycleModule
    from core_data_entities import TempControlConfig

    cycle_module = ConstantWeightCycleModule(device_op)

    def on_cycle_progress(data: dict):
        print("第%d/%d轮: 差值=%.6fg 阈值=%.4fg check_dry=%.4f dry=%.4f" % (
            data["cycle_index"] + 1, data["max_cycles"],
            data["weight_diff"], data["precision"],
            data["check_dry_weight"], data["dry_weight"],
        ))

    def on_cycle_finished(result):
        print("恒重完成: 最终干燥重=%.4fg 轮次=%d 精度达标=%s 最大次数=%s" % (
            result.final_dry_weight, result.total_cycles,
            result.is_precision_met, result.is_max_cycle_reached,
        ))
        for i, rec in enumerate(result.cycle_records):
            print("  第%d轮: check=%.4f dry=%.4f diff=%.6f" %
                  (i + 1, rec.check_dry_weight, rec.dry_weight, rec.weight_diff))

    def on_cycle_error(msg: str):
        print("恒重循环异常: %s" % msg)

    cycle_module.cycle_progress.connect(on_cycle_progress)
    cycle_module.cycle_finished.connect(on_cycle_finished)
    cycle_module.cycle_error.connect(on_cycle_error)

    # 也可以连接透传的子模块信号
    cycle_module.temp_progress.connect(
        lambda d: print("  [温区] %s %.1f℃" % (d["stage"], d["current_temp"]))
    )
    cycle_module.weigh_progress.connect(
        lambda d: print("  [称重] 位号%d 读数%.4fg" % (d["position"], d["weight"]))
    )

    # 构造温度与气路配置
    temp_cfg = TempControlConfig(
        target_temp=105,        # 目标温度 105℃
        constant_duration=600,  # 此处为模板默认，实际由 interval_duration 覆盖
        blower_enable=False,    # 分析水不开鼓风
        nitrogen_enable=True,   # 分析水开氮气
    )

    # 启动恒重循环
    cycle_module.start_cycle(
        temp_config=temp_cfg,
        interval_duration=600,    # 每轮恒温10分钟
        constant_precision=0.001, # 恒重精度 0.001g
        max_cycle_times=3,        # 最多3轮
        correct_diff=0.5000,      # 坩埚校正差值
        init_check_weight=10.0,   # 首轮检查性干燥重 10g
        positions=[1, 2, 3],      # 称重位号
        weigh_scene="分析水恒重", # 场景标记
    )

    # 停止
    # cycle_module.stop()

    return cycle_module


def example_constant_weight_tw(device_op):
    """模块3调用示例: 全水恒重循环（开鼓风）"""
    from constant_weight_module import ConstantWeightCycleModule
    from core_data_entities import TempControlConfig

    cycle_module = ConstantWeightCycleModule(device_op)

    cycle_module.cycle_progress.connect(lambda d: print(
        "全水恒重第%d轮: diff=%.6f" % (d["cycle_index"] + 1, d["weight_diff"])
    ))
    cycle_module.cycle_finished.connect(lambda r: print(
        "全水恒重完成: dry=%.4f cycles=%d" % (r.final_dry_weight, r.total_cycles)
    ))

    temp_cfg = TempControlConfig(
        target_temp=105,
        blower_enable=True,    # 全水开鼓风
        nitrogen_enable=False,
    )

    cycle_module.start_cycle(
        temp_config=temp_cfg,
        interval_duration=300,    # 每轮恒温5分钟
        constant_precision=0.003, # 全水精度 0.003g
        max_cycle_times=3,
        correct_diff=0.5000,
        init_check_weight=50.0,   # 全水样品较重
        positions=[1, 2, 3],
        weigh_scene="全水恒重",
    )
    return cycle_module


# ================================================================
# 多线程运行示例
# ================================================================

def example_multithread(device_op):
    """将模块放入独立线程运行，不阻塞主线程"""
    from PySide2.QtCore import QThread
    from batch_weigh_module import BatchWeighModule

    # 创建工作线程
    worker_thread = QThread()

    # 创建模块（此时属于创建线程）
    weigh_module = BatchWeighModule(device_op)

    # 将模块移动到工作线程
    weigh_module.moveToThread(worker_thread)

    # 连接信号
    weigh_module.weigh_finished.connect(lambda r: print("称重完成"))

    # 线程结束时清理
    worker_thread.started.connect(
        lambda: weigh_module.start_weigh("多线程称重", [1, 2, 3], 0.5)
    )
    worker_thread.finished.connect(weigh_module.deleteLater)
    weigh_module.weigh_finished.connect(worker_thread.quit)

    # 启动线程
    worker_thread.start()

    return worker_thread, weigh_module

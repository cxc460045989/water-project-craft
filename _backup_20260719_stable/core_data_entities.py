# -*- coding: utf-8 -*-
"""核心数据实体与配置类 — 微机全自动水分测定仪底层能力模块
定义试验参数配置类、测试数据实体类，供3个核心模块统一引用。
不包含任何业务逻辑与界面代码。
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN


def bankers_round(value: float, decimals: int) -> float:
    """银行舍入法（四舍六入五成双）— 避免浮点精度问题"""
    d = Decimal(str(value))
    quantize = Decimal('0.' + '0' * decimals)
    return float(d.quantize(quantize, rounding=ROUND_HALF_EVEN))


# ============================================================
# 称重相关数据实体
# ============================================================

@dataclass
class WeighRecord:
    """单次称量记录 — 原始数据与校正后数据物理隔离"""
    position: int             # 样品位号 (1-based)
    sample_name: str = ""     # 样品名称（仅用于数据打标）
    raw_weight: float = 0.0   # 原始天平读数 (g)
    corrected_weight: float = 0.0  # 校正后重量 = 原始重量 + 校正坩埚差值 (g)
    timestamp: str = ""       # 称量时间戳


@dataclass
class BatchWeighResult:
    """批量称重完整结果"""
    scene: str                          # 称重场景标记
    records: List[WeighRecord] = field(default_factory=list)  # 单次称量记录列表
    crucible_correct_diff: float = 0.0  # 使用的校正坩埚差值
    timestamp: str = ""                 # 完成时间戳

    @property
    def raw_weights(self) -> List[float]:
        """原始重量列表（只读视图）"""
        return [r.raw_weight for r in self.records]

    @property
    def corrected_weights(self) -> List[float]:
        """校正后重量列表（只读视图）"""
        return [r.corrected_weight for r in self.records]


# ============================================================
# 控温恒温相关配置与数据
# ============================================================

@dataclass
class TempControlConfig:
    """控温恒温参数配置 — 所有可变参数通过入参传入"""
    target_temp: int = 105         # 目标设定温度 (℃)
    constant_duration: int = 3600  # 恒温总时长 (秒)
    blower_enable: bool = False    # 是否开启鼓风（与氮气互斥）
    nitrogen_enable: bool = False  # 是否开启氮气（鼓风关闭时生效）
    # 内部判定阈值（可配置但通常使用默认值）
    heat_threshold_offset: float = 5.0   # 升温判定偏移量: 温度 >= target_temp - offset 即判定达标
    cmd_alternate_interval: float = 10.0 # 恒温指令交替发送间隔 (秒)
    cmd_stop_advance: float = 30.0       # 提前停止指令交替的时间 (秒)


@dataclass
class TempProgressData:
    """温区进度数据 — 通过信号携带"""
    stage: str            # 当前阶段: "heating" / "holding"
    current_temp: float   # 当前温度 (℃)
    target_temp: int      # 目标温度 (℃)
    remaining_sec: float  # 剩余时间 (秒)
    percent: float        # 完成百分比 (0~100)


# ============================================================
# 恒重循环相关配置与数据
# ============================================================

@dataclass
class ConstantWeightConfig:
    """恒重循环参数配置"""
    temp_config: TempControlConfig = field(default_factory=TempControlConfig)  # 温度与气路配置（透传控温模块）
    interval_duration: int = 300      # 恒重称量间隔时长 (秒) — 每轮循环的恒温时间
    constant_precision: float = 0.001 # 恒重精度阈值 (g)
    max_cycle_times: int = 3          # 最大循环次数（防死循环）
    correct_diff: float = 0.0         # 坩埚校正差值（透传称重模块）
    init_check_weight: float = 0.0    # 首轮检查性干燥重量 (g)


@dataclass
class CycleRecord:
    """单轮循环称重记录"""
    cycle_index: int             # 轮次 (0-based)
    weigh_records: List[WeighRecord] = field(default_factory=list)  # 本轮所有样品称重记录
    check_dry_weight: float = 0.0   # 本轮检查性干燥重量
    dry_weight: float = 0.0         # 本轮干燥后重量
    weight_diff: float = 0.0        # 重量差值 = check_dry_weight - dry_weight


@dataclass
class ConstantWeightResult:
    """恒重循环最终结果"""
    final_dry_weight: float = 0.0            # 最终干燥重量 (g)
    total_cycles: int = 0                    # 实际循环次数
    cycle_records: List[CycleRecord] = field(default_factory=list)  # 每轮称重记录
    is_precision_met: bool = False           # 是否通过精度判定
    is_max_cycle_reached: bool = False       # 是否因达到最大次数而终止


# ============================================================
# 设备操作接口 — 底层命令封装
# ============================================================

class DeviceOperator:
    """设备底层操作封装 — 对 SerialManager + protocol_layer 的统一门面

    供3个核心模块调用，模块不直接操作串口或协议层。
    所有方法均返回操作结果，内部处理重试与异常。
    """

    def __init__(self, serial_mgr):
        """
        参数:
            serial_mgr: SerialManager 实例（已连接）
        """
        self._serial = serial_mgr

    # ---- 基础指令 ----

    def send_fixed_cmd(self, func_code: int, desc: str = "") -> bool:
        """发送固定4字节指令（带上行检测+重试）"""
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_command(func_code)
        return send_cmd_with_uplink_check(self._serial, cmd, desc)

    def send_temp_control(self, temp_c: int, desc: str = "") -> bool:
        """发送控温指令"""
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_temp_control(temp_c)
        return send_cmd_with_uplink_check(self._serial, cmd, desc)

    def send_move_to(self, position: int, desc: str = "") -> bool:
        """发送样盘移动到指定位置指令"""
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_move_to(position)
        return send_cmd_with_uplink_check(self._serial, cmd, desc)

    def send_weight(self, weight_g: float, desc: str = "") -> bool:
        """发送天平数据到仪器"""
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_send_weight(weight_g)
        return send_cmd_with_uplink_check(self._serial, cmd, desc)

    # ---- 上行帧读取 ----

    def read_uplink_frame(self) -> Optional[dict]:
        """读取并解析一帧上行数据
        返回: dict | None  — None 表示无有效帧
            {"temperature": float, "weight": float, "online": int, "btn_pressed": int}
        """
        try:
            raw = self._serial.readAll()
        except Exception:
            return None
        if not raw:
            return None
        from protocol_layer import UplinkBuffer
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        if frames:
            return frames[-1]
        return None

    @property
    def is_connected(self) -> bool:
        return self._serial.is_connected

    @property
    def serial_mgr(self):
        """获取底层 SerialManager 引用（供特殊场景使用）"""
        return self._serial

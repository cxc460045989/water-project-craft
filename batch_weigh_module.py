# -*- coding: utf-8 -*-
"""批量称重模块 — 微机全自动水分测定仪底层能力模块1

全局唯一，所有称重场景复用。
执行完整批量称量流程，自动处理坩埚校正计算，记录原始称重数据。
内部逻辑完全独立，不感知分析水/全水、恒重等业务概念。

技术约束:
  - 继承 QObject，通过信号槽对外传递数据与状态
  - 支持 moveToThread 多线程运行，不阻塞主线程
  - 所有可变参数通过入参传入，禁止硬编码魔法值
  - 原始数据与校正后数据分开存储，物理隔离

用法:
    module = BatchWeighModule(device_op, parent)
    module.weigh_progress.connect(on_progress)
    module.weigh_finished.connect(on_finished)
    module.weigh_error.connect(on_error)
    module.start_weigh(scene="分析水称重", positions=[1,2,3], correct_diff=0.5)
"""

import time
from typing import List, Optional

from PySide2.QtCore import QObject, Signal, QTimer

from core_data_entities import (
    DeviceOperator, WeighRecord, BatchWeighResult,
)
from protocol_layer import CMD

# ======== 可配置默认常量 ========
import os as _os
_SPEED_MODE = _os.environ.get('WATER_SPEED_MODE', '0') == '1'
DEFAULT_STABLE_WAIT_S = 2.0 if _SPEED_MODE else 5.0
DEFAULT_STABLE_SAMPLE_COUNT = 3 if _SPEED_MODE else 10
DEFAULT_STABLE_TOLERANCE_G = 0.01 if _SPEED_MODE else 0.0005
DEFAULT_DESCEND_TIMEOUT_S = 5.0 if _SPEED_MODE else 15.0
DEFAULT_STATE_TICK_MS = 200


def _utc_now_str() -> str:
    """获取当前时间戳字符串"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BatchWeighModule(QObject):
    """批量称重模块 — 所有称重场景复用

    输入参数 (start_weigh):
        scene:         称重场景标记（仅用于数据打标与进度展示，不影响内部逻辑）
        correct_diff:  校正坩埚差值 = 校正坩埚重 - 校正坩埚干燥重
        positions:     样品位号列表 (1-based)

    输出信号:
        weigh_progress: 称重进度
        weigh_finished: 称重完成 BatchWeighResult
        weigh_error:    异常信号
    """

    # ======== 信号定义 ========
    weigh_progress = Signal(dict)
    """称重进度: {"step":int, "total":int, "position":int, "scene":str, "weight":float}"""

    weigh_finished = Signal(object)
    """称重完成: 携带 BatchWeighResult 对象"""

    weigh_error = Signal(str)
    """异常: 携带错误信息"""

    # ======== 状态机常量 ========
    _ST_IDLE = "idle"
    _ST_INIT = "init"
    _ST_MOVE = "move"
    _ST_WAIT_MOVE = "wait_move"
    _ST_TARE = "tare"
    _ST_WAIT_TARE = "wait_tare"
    _ST_DESCEND = "descend"
    _ST_WAIT_DESCEND = "wait_descend"
    _ST_READ = "read"
    _ST_NEXT = "next"
    _ST_DONE = "done"

    def __init__(self, device_op: DeviceOperator, parent: QObject = None):
        """初始化批量称重模块

        参数:
            device_op: DeviceOperator 实例（已连接设备）
            parent:    父 QObject
        """
        super().__init__(parent)
        self._dev = device_op

        # 运行时状态
        self._state = self._ST_IDLE
        self._scene = ""
        self._positions: List[int] = []
        self._correct_diff = 0.0
        self._pos_index = 0
        self._records: List[WeighRecord] = []
        self._running = False

        # 稳定读数采样缓冲
        self._weight_samples: List[float] = []

        # 阶段起始时间（用于超时判定）
        self._phase_start = 0.0

        # QTimer 驱动状态机
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    # ================================================================
    # 公共接口
    # ================================================================

    def start_weigh(self, scene: str, positions: List[int], correct_diff: float):
        """启动批量称重

        参数:
            scene:        称重场景标记（仅用于数据打标与进度展示）
            positions:    样品位号列表 (1-based, 如 [1,2,3,...])
            correct_diff: 校正坩埚差值 (g)
                          corrected_weight = raw_weight + correct_diff
        """
        if self._running:
            self.weigh_error.emit("称重模块已在运行中，不可重复启动")
            return
        if not positions:
            self.weigh_error.emit("样品位号列表为空")
            return

        self._scene = scene
        self._positions = list(positions)
        self._correct_diff = correct_diff
        self._pos_index = 0
        self._records = []
        self._weight_samples = []
        self._running = True
        self._state = self._ST_INIT

        from logging_util import logger
        logger.info("[BATCH_WEIGH] 启动 scene=%s positions=%s diff=%.4f" %
                     (scene, str(positions), correct_diff))
        self._timer.start(DEFAULT_STATE_TICK_MS)

    def stop(self):
        """停止称重流程 — 安全终止，不发送完成信号"""
        self._running = False
        self._timer.stop()
        self._state = self._ST_IDLE
        from logging_util import logger
        logger.info("[BATCH_WEIGH] 已停止")

    def reset(self):
        """重置模块 — 清除所有运行数据"""
        self.stop()
        self._scene = ""
        self._positions = []
        self._correct_diff = 0.0
        self._pos_index = 0
        self._records = []
        self._weight_samples = []

    @property
    def is_running(self) -> bool:
        return self._running

    # ================================================================
    # 状态机主循环 (QTimer 200ms)
    # ================================================================

    def _on_tick(self):
        if not self._running:
            self._timer.stop()
            return
        handler = getattr(self, "_handle_" + self._state, None)
        if handler:
            handler()

    # ================================================================
    # 状态处理函数
    # ================================================================

    def _handle_init(self):
        """初始化: 关炉盖，准备称重"""
        self._dev.send_fixed_cmd(CMD.CLOSE_LID, "关炉盖(称重准备)")
        self._emit_progress(0, len(self._positions), 0)
        self._pos_index = 0
        self._phase_start = time.time()
        self._state = self._ST_MOVE

    def _handle_move(self):
        """移动到当前样品位"""
        if self._pos_index >= len(self._positions):
            self._state = self._ST_DONE
            return
        pos = self._positions[self._pos_index]
        self._dev.send_move_to(pos, "移动到%d号位" % pos)
        self._phase_start = time.time()
        self._state = self._ST_WAIT_MOVE

    def _handle_wait_move(self):
        """等待移动完成（收到上行帧即认为完成）"""
        frame = self._dev.read_uplink_frame()
        if frame is not None:
            self._state = self._ST_TARE
            return
        if time.time() - self._phase_start > DEFAULT_DESCEND_TIMEOUT_S:
            self._state = self._ST_TARE

    def _handle_tare(self):
        """发送天平清零（去皮）"""
        self._dev.send_fixed_cmd(CMD.TARE, "天平清零")
        self._phase_start = time.time()
        self._state = self._ST_WAIT_TARE

    def _handle_wait_tare(self):
        """等待去皮后短延时"""
        if time.time() - self._phase_start > 0.5:
            self._state = self._ST_DESCEND

    def _handle_descend(self):
        """样盘下降到低位"""
        self._dev.send_fixed_cmd(CMD.SAMPLE_PLATE_DOWN, "样盘下降")
        self._phase_start = time.time()
        self._state = self._ST_WAIT_DESCEND

    def _handle_wait_descend(self):
        """等待样盘下降完成"""
        frame = self._dev.read_uplink_frame()
        if frame is not None:
            self._phase_start = time.time()
            self._state = self._ST_READ
            self._weight_samples = []
            return
        if time.time() - self._phase_start > DEFAULT_DESCEND_TIMEOUT_S:
            self._state = self._ST_READ
            self._weight_samples = []

    def _handle_read(self):
        """持续读取天平读数直至稳定，记录原始与校正重量"""
        frame = self._dev.read_uplink_frame()
        if frame is not None:
            w = frame.get("weight", 0.0)
            self._weight_samples.append(w)
            pos = self._positions[self._pos_index]
            self._emit_progress(self._pos_index + 1, len(self._positions), pos, w)

        # 判定稳定: 最近N个样本波动 <= 容差
        if len(self._weight_samples) >= DEFAULT_STABLE_SAMPLE_COUNT:
            recent = self._weight_samples[-DEFAULT_STABLE_SAMPLE_COUNT:]
            if max(recent) - min(recent) <= DEFAULT_STABLE_TOLERANCE_G:
                self._record_weight()
                return

        # 超时保护: 取最近样本均值
        if time.time() - self._phase_start > DEFAULT_STABLE_WAIT_S + 10.0:
            self._record_weight()

    def _record_weight(self):
        """记录当前样品位的原始重量与校正后重量"""
        if self._weight_samples:
            raw_weight = round(
                sum(self._weight_samples[-5:]) / min(5, len(self._weight_samples)), 4
            )
        else:
            raw_weight = 0.0
        corrected = round(raw_weight + self._correct_diff, 4)
        pos = self._positions[self._pos_index]
        record = WeighRecord(
            position=pos,
            sample_name="",
            raw_weight=raw_weight,
            corrected_weight=corrected,
            timestamp=_utc_now_str(),
        )
        self._records.append(record)
        from logging_util import logger
        logger.info("[BATCH_WEIGH] pos=%d raw=%.4f corrected=%.4f" %
                     (pos, raw_weight, corrected))
        self._state = self._ST_NEXT

    def _handle_next(self):
        """前进到下一个样品位或完成"""
        self._pos_index += 1
        self._weight_samples = []
        if self._pos_index < len(self._positions):
            self._state = self._ST_MOVE
        else:
            self._state = self._ST_DONE

    def _handle_done(self):
        """称重完成: 样盘上升 → 开炉盖 → 发信号"""
        self._timer.stop()
        self._running = False

        self._dev.send_fixed_cmd(CMD.SAMPLE_PLATE_UP, "样盘上升")
        self._dev.send_fixed_cmd(CMD.OPEN_LID, "打开炉盖")

        result = BatchWeighResult(
            scene=self._scene,
            records=self._records,
            crucible_correct_diff=self._correct_diff,
            timestamp=_utc_now_str(),
        )
        from logging_util import logger
        logger.info("[BATCH_WEIGH] 完成 scene=%s 共%d个样品" %
                     (self._scene, len(self._records)))
        self._state = self._ST_IDLE
        self.weigh_finished.emit(result)

    def _handle_idle(self):
        pass

    def _emit_progress(self, step: int, total: int, position: int, weight: float = 0.0):
        self.weigh_progress.emit({
            "step": step,
            "total": total,
            "position": position,
            "scene": self._scene,
            "weight": weight,
        })

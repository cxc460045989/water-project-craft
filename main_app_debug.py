# -*- coding: utf-8 -*-
"""调试版入口 - Mock仪器模拟器 + 控制台串口日志 + 故障注入
无需硬件，双击运行即可用完整UI测试全部功能，同时控制台输出所有串口通讯日志。

用法:
    python main_app_debug.py
"""
import sys, os, datetime

os.environ['WATER_MODE'] = 'mock'
os.environ['WATER_SPEED_MODE'] = '1'

_ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
TAG = "[调试-串口] "

print("=" * 60)
print("  微机全自动水分测定仪 — Mock 调试版")
print("  统一适配器模式 + 串口日志全开 + 故障注入")
print("=" * 60)
print()

# ===== 注入调试日志到 serial_comm =====
import serial_comm

_send_orig = serial_comm.SerialManager.send

def _debug_send(self, data):
    hex_str = " ".join(f"{b:02X}" for b in data)
    print(TAG + _ts() + " 发送(len=%d) HEX: %s" % (len(data), hex_str))
    return _send_orig(self, data)

serial_comm.SerialManager.send = _debug_send

print(TAG + "调试日志补丁已注入")


# ===== 故障注入控制面板 =====
from PySide2.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QDoubleSpinBox, QCheckBox,
    QSpinBox,
)
from PySide2.QtCore import Qt, QTimer


class FaultInjectionPanel(QWidget):
    """故障注入控制面板 — 模拟各种硬件异常"""

    def __init__(self, sim):
        super().__init__()
        self._sim = sim
        self.setWindowTitle("故障注入控制台")
        self.setFixedSize(360, 300)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_stats)
        self._timer.start(1000)

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 10, 12, 10)

        # 丢帧
        grp_drop = QGroupBox("上行帧丢帧")
        dlo = QHBoxLayout(grp_drop)
        self._spin_drop = QDoubleSpinBox()
        self._spin_drop.setRange(0, 1.0)
        self._spin_drop.setSingleStep(0.05)
        self._spin_drop.setDecimals(2)
        self._spin_drop.setValue(0)
        self._spin_drop.setSuffix(" 概率")
        self._spin_drop.valueChanged.connect(self._apply)
        dlo.addWidget(QLabel("丢帧率:"))
        dlo.addWidget(self._spin_drop)
        lo.addWidget(grp_drop)

        # ACK 延迟
        grp_ack = QGroupBox("ACK 延迟")
        alo = QHBoxLayout(grp_ack)
        self._spin_ack = QSpinBox()
        self._spin_ack.setRange(0, 5000)
        self._spin_ack.setValue(0)
        self._spin_ack.setSuffix(" ms")
        self._spin_ack.valueChanged.connect(self._apply)
        alo.addWidget(QLabel("延迟:"))
        alo.addWidget(self._spin_ack)
        lo.addWidget(grp_ack)

        # 温度噪声
        grp_temp = QGroupBox("温度噪声")
        tlo = QHBoxLayout(grp_temp)
        self._spin_temp_noise = QDoubleSpinBox()
        self._spin_temp_noise.setRange(0, 10.0)
        self._spin_temp_noise.setSingleStep(0.5)
        self._spin_temp_noise.setValue(0)
        self._spin_temp_noise.setSuffix(" C")
        self._spin_temp_noise.valueChanged.connect(self._apply)
        tlo.addWidget(QLabel("噪声:"))
        tlo.addWidget(self._spin_temp_noise)
        lo.addWidget(grp_temp)

        # 天平漂移
        grp_drift = QGroupBox("天平漂移")
        drlo = QHBoxLayout(grp_drift)
        self._spin_drift = QDoubleSpinBox()
        self._spin_drift.setRange(0, 1.0)
        self._spin_drift.setSingleStep(0.001)
        self._spin_drift.setDecimals(4)
        self._spin_drift.setValue(0)
        self._spin_drift.setSuffix(" g/次")
        self._spin_drift.valueChanged.connect(self._apply)
        drlo.addWidget(QLabel("漂移:"))
        drlo.addWidget(self._spin_drift)
        lo.addWidget(grp_drift)

        # 温度传感器故障
        self._chk_temp_fault = QCheckBox("温度传感器故障 (锁定 999.9C)")
        self._chk_temp_fault.toggled.connect(self._apply)
        lo.addWidget(self._chk_temp_fault)

        # 统计
        self._lbl_stats = QLabel("丢帧: 0 | ACK延迟: 0")
        self._lbl_stats.setStyleSheet("font-size:12px; color:#666; padding:4px;")
        lo.addWidget(self._lbl_stats)

        # 按钮
        btn_reset = QPushButton("重置所有故障")
        btn_reset.clicked.connect(self._reset_all)
        lo.addWidget(btn_reset)

    def _apply(self):
        cfg = {
            "drop_uplink_rate": self._spin_drop.value(),
            "ack_delay_ms": self._spin_ack.value(),
            "temp_noise": self._spin_temp_noise.value(),
            "weight_drift": self._spin_drift.value(),
            "temp_sensor_fault": self._chk_temp_fault.isChecked(),
        }
        self._sim.enable_fault_injection(cfg)

    def _reset_all(self):
        self._spin_drop.setValue(0)
        self._spin_ack.setValue(0)
        self._spin_temp_noise.setValue(0)
        self._spin_drift.setValue(0)
        self._chk_temp_fault.setChecked(False)
        self._sim.disable_fault_injection()

    def _refresh_stats(self):
        st = self._sim.fault_stats
        self._lbl_stats.setText(
            "丢帧: %d | ACK延迟: %d" %
            (st["dropped_frames"], st["delayed_acks"])
        )


# ===== 启动 =====
from main_app import main
main()

# 故障注入面板 (挂在 MoistureAnalyzer 实例上)
app = QApplication.instance()
if app:
    for widget in app.topLevelWidgets():
        if hasattr(widget, '_mock_sim') and widget._mock_sim is not None:
            fault_panel = FaultInjectionPanel(widget._mock_sim)
            fault_panel.show()
            break

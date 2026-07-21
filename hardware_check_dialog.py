# -*- coding: utf-8 -*-
"""硬件检测对话框 - 微机全自动水分测定仪
框架: PySide2 (Qt5) - 兼容Windows 7 / 麒麟Linux x86/ARM64
"""

import sys
from PySide2.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QPushButton, QLabel, QLineEdit, QCheckBox,
)
from PySide2.QtCore import Qt
from PySide2.QtGui import QFont
from button_styles import apply_button_types
from button_styles import apply_button_types
from logging_util import logger


# ============================================================
# 数码管显示标签
# ============================================================
class DigitLabel(QLabel):
    """黑底绿字数码管风格标签"""
    def __init__(self, text="000", font_size=36, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: #000000;
                color: #00FF00;
                font-size: {font_size}px;
                font-family: "Courier New", "Consolas", "DejaVu Sans Mono", monospace;
                font-weight: bold;
                padding: 4px 12px;
                border: 1px solid #555555;
                border-radius: 4px;
            }}
        """)
        self.setMinimumWidth(font_size * 3)


# ============================================================
# 硬件检测对话框
# ============================================================
class HardwareCheckDialog(QDialog):
    """硬件检测弹窗"""

    def __init__(self, parent=None, serial_mgr=None):
        super().__init__(parent)
        self._mgr = serial_mgr
        self._buf = None
        self._status_callback = None
        self.setWindowTitle("硬件检测")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #E8EBF0;
            }
            QGroupBox {
                background-color: #F2F4F7;
                border: 1px solid #C8CED8;
                border-radius: 6px;
                margin-top: 14px;
                padding: 18px 14px 12px 14px;
                font-size: 14px;
                font-weight: bold;
                color: #1F2937;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 12px;
                background-color: #E8EBF0;
                border: 1px solid #C8CED8;
                border-radius: 3px;
                left: 10px;
            }

            QLineEdit {
                background-color: #FFFFFF;
                color: #1F2937;
                border: 1px solid #B0B8C4;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 13px;
                min-height: 24px;
            }
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #1F2937;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QLabel {
                font-size: 13px;
                color: #1F2937;
            }
        """)
        self._build_ui()
        self._load_temp_corr_from_db()
        self.setFixedSize(540, 570)
        if self._mgr:
            from protocol_layer import UplinkBuffer
            self._buf = UplinkBuffer()
            self._mgr.data_received.connect(self._on_serial_data)
            self._mgr.error_occurred.connect(self._on_serial_error)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ---- 第一组：系统检测 ----
        grp1 = QGroupBox(" 系统检测 ")
        gl = QGridLayout(grp1)
        gl.setSpacing(8)

        btn=QPushButton("样盘上升");btn.clicked.connect(lambda:self.send_command("样盘上升",0x14));gl.addWidget(btn,0,0)
        btn=QPushButton("移动一位");btn.clicked.connect(lambda:self.send_command("移动一位",0x29));gl.addWidget(btn,0,1)
        btn=QPushButton("样盘下降");btn.clicked.connect(lambda:self.send_command("样盘下降",0x15));gl.addWidget(btn,1,0)
        btn=QPushButton("移到1号位");btn.clicked.connect(lambda:self.send_command("移到1号位",0x30));gl.addWidget(btn,1,1)

        h = QHBoxLayout()
        h.setSpacing(8)
        btn_move=QPushButton("移动到指定样位");btn_move.setMinimumWidth(142);btn_move.clicked.connect(self._on_move_to_pos)
        h.addWidget(btn_move)
        self._le_pos = QLineEdit("1")
        self._le_pos.setFixedWidth(50)
        self._le_pos.setAlignment(Qt.AlignCenter)
        h.addWidget(self._le_pos)
        h.addWidget(QLabel(" 号样位 "))
        gl.addLayout(h, 2, 0, 1, 2)

        cb_widget = QWidget()
        cb_layout = QGridLayout(cb_widget)
        cb_layout.setContentsMargins(20, 10, 20, 10)
        cb_layout.setSpacing(8)
        self._cb_lid = QCheckBox(" 炉盖 ")
        self._cb_lid.toggled.connect(lambda s: self._on_checkbox_toggled(s, "炉盖", 0x18, 0x19))
        cb_layout.addWidget(self._cb_lid, 0, 0)
        self._cb_heat = QCheckBox(" 加热 ")
        self._cb_heat.toggled.connect(lambda s: self._on_checkbox_toggled(s, "加热", 0x57, 0x1B))
        cb_layout.addWidget(self._cb_heat, 0, 1)
        self._cb_fan = QCheckBox(" 风扇 ")
        self._cb_fan.toggled.connect(lambda s: self._on_checkbox_toggled(s, "风扇", 0x1C, 0x1D))
        cb_layout.addWidget(self._cb_fan, 1, 0)
        self._cb_n2 = QCheckBox(" 氮气 ")
        self._cb_n2.toggled.connect(lambda s: self._on_checkbox_toggled(s, "氮气", 0x1E, 0x1F))
        cb_layout.addWidget(self._cb_n2, 1, 1)
        gl.addWidget(cb_widget, 0, 2, 3, 1)

        main_layout.addWidget(grp1)

        # ---- 第二组：炉膛温度 ----
        grp2 = QGroupBox(" 炉膛温度 ")
        h2 = QHBoxLayout(grp2)
        h2.setSpacing(16)
        h2.setContentsMargins(4, 0, 4, 0)

        # 左侧温度显示
        left2 = QHBoxLayout()
        left2.setSpacing(8)
        left2.addWidget(QLabel(" 温度 "))
        self.temp_digit = DigitLabel("000", font_size=42)
        self.temp_digit.setFixedWidth(150)
        left2.addWidget(self.temp_digit)
        left2.addWidget(QLabel(" ℃ "))
        h2.addLayout(left2)
        h2.addStretch()

        # 右侧校准区
        right2 = QVBoxLayout()
        right2.setSpacing(8)
        right2.addStretch()
        right2.addWidget(QLabel(" 校准 "))
        form2 = QGridLayout()
        form2.setSpacing(8)
        form2.addWidget(QLabel(" 分析水 "), 0, 0)
        self.le_aw_temp_corr = QLineEdit("0")
        self.le_aw_temp_corr.setFixedWidth(80)
        self.le_aw_temp_corr.setAlignment(Qt.AlignCenter)
        self.le_aw_temp_corr.editingFinished.connect(self._on_temp_corr_changed)
        form2.addWidget(self.le_aw_temp_corr, 0, 1)
        form2.addWidget(QLabel(" ℃ "), 0, 2)
        form2.addWidget(QLabel(" 全水 "), 1, 0)
        self.le_tw_temp_corr = QLineEdit("0")
        self.le_tw_temp_corr.setFixedWidth(80)
        self.le_tw_temp_corr.setAlignment(Qt.AlignCenter)
        self.le_tw_temp_corr.editingFinished.connect(self._on_temp_corr_changed)
        form2.addWidget(self.le_tw_temp_corr, 1, 1)
        form2.addWidget(QLabel(" ℃ "), 1, 2)
        right2.addLayout(form2)
        right2.addStretch()
        h2.addLayout(right2)

        main_layout.addWidget(grp2)

        # ---- 第三组：天平 ----
        grp3 = QGroupBox(" 天平 ")
        h3 = QHBoxLayout(grp3)
        h3.setSpacing(16)
        h3.setContentsMargins(4, 0, 4, 0)

        # 左侧数码显示
        left3 = QHBoxLayout()
        left3.setSpacing(8)
        self.scale_digit = DigitLabel("000.0000", font_size=52)
        self.scale_digit.setFixedWidth(300)
        left3.addWidget(self.scale_digit)
        unit_label = QLabel(" g ")
        unit_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #1F2937;")
        left3.addWidget(unit_label)
        left3.addStretch()
        h3.addLayout(left3)

        # 右侧按钮
        right3 = QVBoxLayout()
        right3.setSpacing(8)
        btn=QPushButton("清零");btn.clicked.connect(lambda:self.send_command("天平清零",0x16));right3.addWidget(btn)
        btn=QPushButton("校准");btn.clicked.connect(lambda:self.send_command("天平校准",0x17));right3.addWidget(btn)
        right3.addStretch()
        h3.addLayout(right3)

        main_layout.addWidget(grp3)

        # ---- ??? ----
        self._status = QLabel("就绪")
        self._status.setStyleSheet("font-size: 13px; color: #1F2937; padding: 4px 8px; background-color: #FFFFFF; border: 1px solid #B0B8C4; border-radius: 3px;")
        main_layout.addWidget(self._status)


    # ---- 温度校准 ----
    def _get_aw_temp_corr(self):
        try:
            return float(self.le_aw_temp_corr.text() or "0")
        except (ValueError, AttributeError):
            return 0.0

    def _get_tw_temp_corr(self):
        try:
            return float(self.le_tw_temp_corr.text() or "0")
        except (ValueError, AttributeError):
            return 0.0

    def _load_temp_corr_from_db(self):
        """从数据库加载温度校准值到输入框"""
        try:
            from db import load_params
            params = load_params()
            aw = params.get("aw_temp_corr", 0)
            tw = params.get("tw_temp_corr", 0)
            self.le_aw_temp_corr.setText("{:.1f}".format(float(aw)))
            self.le_tw_temp_corr.setText("{:.1f}".format(float(tw)))
        except Exception:
            pass

    def _on_temp_corr_changed(self):
        """温度校准值修改后存入DB"""
        try:
            aw = self._get_aw_temp_corr()
            tw = self._get_tw_temp_corr()
            from db import save_params
            save_params(aw_temp_corr=aw, tw_temp_corr=tw)
        except Exception:
            pass

# ============================================================

    # ---- 串口通讯 ----
    def _on_serial_data(self, data):
        if not self._buf:
            return
        frames = self._buf.feed(data)
        for f in frames:
            # 温度校准: 默认用分析水校准值显示
            aw_corr = self._get_aw_temp_corr()
            cal_temp = f["temperature"] + aw_corr
            self.temp_digit.setText("%.1f" % cal_temp)
            if f["weight"] >= 0:
                self.scale_digit.setText("%.4f" % f["weight"])
            if self._status_callback:
                self._status_callback(f)

    def _on_serial_error(self, msg):
        self._status.setText("错误: " + msg)

    def _on_move_to_pos(self):
        """读取输入框样位号，可选自动下降"""
        try:
            pos = int(self._le_pos.text().strip())
        except (ValueError, AttributeError):
            logger.info("[HARDWARE][" + (self._mgr.port_name if self._mgr else "?") + "] 样位号无效")
            self._status.setText("样位号无效")
            return
        from protocol_layer import CommandBuilder
        cmd = CommandBuilder.build_move_to(pos)
        self.send_command("移动到" + str(pos) + "号位", cmd)

    def send_command(self, label, func_code_or_bytes):
        if not self._mgr or not self._mgr.is_connected:
            logger.info("[HARDWARE][" + (self._mgr.port_name if self._mgr else "?") + "] " + label + " 失败: 串口未连接")
            self._status.setText("串口未连接")
            return
        from protocol_layer import CommandBuilder, CMD
        if isinstance(func_code_or_bytes, bytes):
            cmd = func_code_or_bytes
        else:
            cmd = CommandBuilder.build_command(func_code_or_bytes)
        self._status.setText(label + " ...")
        # 硬件检测为手动测试场景，直接发送不重试（避免机械指令被重复执行）
        self._do_send(cmd, label)


    def _on_checkbox_toggled(self, state, label, on_code, off_code):
        """CheckBox 勾选/取消 -> 发送对应串口指令"""
        if state and on_code == 0x57:
            from PySide2.QtWidgets import QInputDialog
            dlg = QInputDialog(self)
            dlg.setWindowTitle("设定温度")
            dlg.setLabelText("目标温度(℃):")
            dlg.setIntValue(105)
            dlg.setIntRange(0, 999)
            temp_ok = dlg.exec_()
            if not temp_ok:
                sender = self.sender()
                if sender:
                    sender.blockSignals(True)
                    sender.setChecked(False)
                    sender.blockSignals(False)
                return
            temp_val = dlg.intValue()
            from protocol_layer import CommandBuilder, CMD
            cmd = CommandBuilder.build_temp_control(temp_val)
            self._status.setText(label + " 开 ...")
            self._do_send(cmd, label + " 开 " + str(temp_val) + "℃")
            return
        func_code = on_code if state else off_code
        self.send_command(label + (" 开" if state else " 关"), func_code)

    def _do_send(self, cmd, label):
        """直接发送指令，不重试（硬件检测场景每次点击只应执行一次）"""
        if not self._mgr or not self._mgr.is_connected:
            return
        n = self._mgr.send(cmd)
        if n > 0:
            logger.info("[HARDWARE][" + (self._mgr.port_name if self._mgr else "?") + "] " + label + " 已发送")
            self._status.setText(label + " 已发送")
        else:
            logger.info("[HARDWARE][" + (self._mgr.port_name if self._mgr else "?") + "] " + label + " 发送失败")
            self._status.setText(label + " 发送失败")

    def set_status_callback(self, callback):
        self._status_callback = callback

# 独立测试入口
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dlg = HardwareCheckDialog()
    dlg.exec_()



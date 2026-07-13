# -*- coding: utf-8 -*-
"""试验参数设置对话框 - 微机全自动水分测定仪
框架: PySide2 (Qt5) - 兼容Windows 7 / 麒麟Linux x86/ARM64
"""

import sys
from PySide2.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QPushButton, QLabel, QLineEdit, QCheckBox, QRadioButton, QComboBox,
)
from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QFont
from button_styles import apply_button_types
from button_styles import apply_button_types
from db import load_params, save_params, load_techs, save_tech


# ============================================================
# 试验参数设置对话框
# ============================================================
class SettingsDialog(QDialog):
    """试验参数设置弹窗"""

    params_changed = Signal()  # 通知主界面参数已变更

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("试验参数")
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
            QRadioButton {
                font-size: 13px;
                font-weight: bold;
                color: #1F2937;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
            }
            QComboBox {
                background-color: #FFFFFF;
                color: #1F2937;
                border: 1px solid #B0B8C4;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 13px;
                min-height: 24px;
            }

            QLabel {
                font-size: 13px;
                color: #1F2937;
            }
        """)
        self._build_ui()
        self.setFixedSize(640, 720)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ========== 顶部区域 ==========
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)

        # -- 左侧：测试方式 --
        grp_method = QGroupBox(" 测试方式 ")
        method_layout = QVBoxLayout(grp_method)
        method_layout.setSpacing(8)
        self.rb_gb = QRadioButton(" 国标法 ")
        self.rb_gb.setChecked(True)
        self.rb_kf = QRadioButton(" 快速法 ")
        self.rb_custom = QRadioButton(" 自定义 ")
        method_layout.addWidget(self.rb_gb)
        method_layout.addWidget(self.rb_kf)
        method_layout.addWidget(self.rb_custom)
        method_layout.addStretch()
        top_layout.addWidget(grp_method)

        # -- 右侧：测试单位 + 化验员 --
        right_top_layout = QVBoxLayout()
        right_top_layout.setSpacing(8)

        unit_count_row = QHBoxLayout()
        unit_count_row.setSpacing(10)
        grp_unit = QGroupBox(" 测试单位 ")
        unit_layout = QVBoxLayout(grp_unit)
        self.le_unit = QLineEdit()
        self.le_unit.setPlaceholderText("")
        unit_layout.addWidget(self.le_unit)
        unit_count_row.addWidget(grp_unit)

        grp_count = QGroupBox(" 样位数量 ")
        count_layout = QVBoxLayout(grp_count)
        self.le_sample_count = QLineEdit()
        self.le_sample_count.setPlaceholderText("9~50")
        count_layout.addWidget(self.le_sample_count)
        unit_count_row.addWidget(grp_count)

        right_top_layout.addLayout(unit_count_row)

        grp_tech = QGroupBox(" 化验员 ")
        tech_layout = QHBoxLayout(grp_tech)
        tech_layout.setSpacing(6)
        self.tech_inputs = []
        for i in range(6):
            le = QLineEdit()
            le.setPlaceholderText("")
            self.tech_inputs.append(le)
            tech_layout.addWidget(le)
        right_top_layout.addWidget(grp_tech)

        top_layout.addLayout(right_top_layout)
        main_layout.addLayout(top_layout)

        # ========== 中部：控温控时 ==========
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(10)

        # -- 左侧：分析水控温控时 --
        grp_aw = QGroupBox(" 分析水控温控时 ")
        aw_layout = QFormLayout(grp_aw)
        aw_layout.setSpacing(8)
        aw_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h1 = QHBoxLayout(); h1.setSpacing(6)
        self.le_aw_temp = QLineEdit("105"); self.le_aw_temp.setFixedWidth(80); self.le_aw_temp.setAlignment(Qt.AlignCenter)
        h1.addWidget(self.le_aw_temp); h1.addWidget(QLabel(" ℃ "))
        aw_layout.addRow(" 恒温温度 ", h1)

        h2 = QHBoxLayout(); h2.setSpacing(6)
        self.le_aw_time = QLineEdit("60"); self.le_aw_time.setFixedWidth(80); self.le_aw_time.setAlignment(Qt.AlignCenter)
        h2.addWidget(self.le_aw_time); h2.addWidget(QLabel(" 分钟 "))
        aw_layout.addRow(" 恒温时间 ", h2)

        self.cb_aw_const = QCheckBox(" 恒重检查 ")
        self.cb_aw_const.setChecked(True)
        aw_layout.addRow("", self.cb_aw_const)

        h3 = QHBoxLayout(); h3.setSpacing(6)
        self.le_aw_prec = QLineEdit("0.0010"); self.le_aw_prec.setFixedWidth(80); self.le_aw_prec.setAlignment(Qt.AlignCenter)
        h3.addWidget(self.le_aw_prec); h3.addWidget(QLabel(" g "))
        aw_layout.addRow(" 设置精度 ", h3)

        h4 = QHBoxLayout(); h4.setSpacing(6)
        self.le_aw_interval = QLineEdit("5"); self.le_aw_interval.setFixedWidth(80); self.le_aw_interval.setAlignment(Qt.AlignCenter)
        h4.addWidget(self.le_aw_interval); h4.addWidget(QLabel(" 分钟 "))
        aw_layout.addRow(" 称量间隔 ", h4)

        mid_layout.addWidget(grp_aw)

        # -- 右侧：全水控温控时 --
        grp_tw = QGroupBox(" 全水控温控时 ")
        tw_layout = QFormLayout(grp_tw)
        tw_layout.setSpacing(8)
        tw_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h5 = QHBoxLayout(); h5.setSpacing(6)
        self.le_tw_temp = QLineEdit("105"); self.le_tw_temp.setFixedWidth(80); self.le_tw_temp.setAlignment(Qt.AlignCenter)
        h5.addWidget(self.le_tw_temp); h5.addWidget(QLabel(" ℃ "))
        tw_layout.addRow(" 恒温温度 ", h5)

        h6 = QHBoxLayout(); h6.setSpacing(6)
        self.le_tw_time = QLineEdit("60"); self.le_tw_time.setFixedWidth(80); self.le_tw_time.setAlignment(Qt.AlignCenter)
        h6.addWidget(self.le_tw_time); h6.addWidget(QLabel(" 分钟 "))
        tw_layout.addRow(" 恒温时间 ", h6)

        self.cb_tw_const = QCheckBox(" 恒重检查 ")
        self.cb_tw_const.setChecked(True)
        tw_layout.addRow("", self.cb_tw_const)

        h7 = QHBoxLayout(); h7.setSpacing(6)
        self.le_tw_prec = QLineEdit("0.0030"); self.le_tw_prec.setFixedWidth(80); self.le_tw_prec.setAlignment(Qt.AlignCenter)
        h7.addWidget(self.le_tw_prec); h7.addWidget(QLabel(" g "))
        tw_layout.addRow(" 设置精度 ", h7)

        h8 = QHBoxLayout(); h8.setSpacing(6)
        self.le_tw_interval = QLineEdit("5"); self.le_tw_interval.setFixedWidth(80); self.le_tw_interval.setAlignment(Qt.AlignCenter)
        h8.addWidget(self.le_tw_interval); h8.addWidget(QLabel(" 分钟 "))
        tw_layout.addRow(" 称量间隔 ", h8)

        mid_layout.addWidget(grp_tw)
        main_layout.addLayout(mid_layout)

        # ========== 底部区域 ==========
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        # -- 左侧：参数区 --
        left_bottom = QWidget()
        left_form = QFormLayout(left_bottom)
        left_form.setSpacing(8)
        left_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        left_form.setContentsMargins(0, 0, 0, 0)

        self.cb_weigh = QComboBox()
        self.cb_weigh.addItems(["批量称坩埚，批量称样品", "批量称坩埚，单独称样品"])
        left_form.addRow(" 称重方式 ", self.cb_weigh)

        h9 = QHBoxLayout(); h9.setSpacing(2)
        self.le_tw_low = QLineEdit("9.0000"); self.le_tw_low.setFixedWidth(80); self.le_tw_low.setAlignment(Qt.AlignCenter)
        self.le_tw_high = QLineEdit("12.0000"); self.le_tw_high.setFixedWidth(80); self.le_tw_high.setAlignment(Qt.AlignCenter)
        h9.addWidget(self.le_tw_low); h9.addSpacing(4); h9.addWidget(QLabel("-")); h9.addSpacing(4); h9.addWidget(self.le_tw_high); h9.addSpacing(4); h9.addWidget(QLabel("g"))
        h9.addStretch()
        left_form.addRow(" 全水样重 ", h9)

        h10 = QHBoxLayout(); h10.setSpacing(2)
        self.le_aw_low = QLineEdit("0.9000"); self.le_aw_low.setFixedWidth(80); self.le_aw_low.setAlignment(Qt.AlignCenter)
        self.le_aw_high = QLineEdit("1.1000"); self.le_aw_high.setFixedWidth(80); self.le_aw_high.setAlignment(Qt.AlignCenter)
        h10.addWidget(self.le_aw_low); h10.addSpacing(4); h10.addWidget(QLabel("-")); h10.addSpacing(4); h10.addWidget(self.le_aw_high); h10.addSpacing(4); h10.addWidget(QLabel("g"))
        h10.addStretch()
        left_form.addRow(" 分析水样重 ", h10)

        h11 = QHBoxLayout(); h11.setSpacing(6)
        self.le_tw_corr = QLineEdit("0.00"); self.le_tw_corr.setFixedWidth(80); self.le_tw_corr.setAlignment(Qt.AlignCenter)
        h11.addWidget(self.le_tw_corr); h11.addWidget(QLabel(" % "))
        left_form.addRow(" 全水校正 ", h11)

        h12 = QHBoxLayout(); h12.setSpacing(6)
        self.le_aw_corr = QLineEdit("0.00"); self.le_aw_corr.setFixedWidth(80); self.le_aw_corr.setAlignment(Qt.AlignCenter)
        h12.addWidget(self.le_aw_corr); h12.addWidget(QLabel(" % "))
        left_form.addRow(" 分析水校正 ", h12)

        bottom_layout.addWidget(left_bottom, 1)

        # -- 右侧：复选框区 + 按钮 --
        right_bottom = QVBoxLayout()
        right_bottom.setSpacing(6)


        # ---- 串口选择 ----
        port_layout = QHBoxLayout()
        port_layout.setSpacing(8)
        port_layout.addWidget(QLabel(" 串口号 "))
        self.cb_com_port = QComboBox()
        self.cb_com_port.addItems(["COM1", "COM2"])
        self.cb_com_port.currentTextChanged.connect(self._save_com_port)
        port_layout.addWidget(self.cb_com_port)
        port_layout.addStretch()
        right_bottom.addLayout(port_layout)
        right_bottom.addSpacing(4)

        self.cb_aw_fan = QCheckBox(" 分析水鼓风 ")
        self.cb_tw_fan = QCheckBox(" 全水鼓风 ")
        self.cb_tw_fan.setChecked(True)
        self.cb_beep = QCheckBox(" 称重提示音 ")
        self.cb_beep.setChecked(True)
        self.cb_retest = QCheckBox(" 开始测试后复检样品重量 ")
        self.cb_autoclear = QCheckBox(" 测试完成后自动清空测试数据 ")

        right_bottom.addWidget(self.cb_aw_fan)
        right_bottom.addWidget(self.cb_tw_fan)
        right_bottom.addWidget(self.cb_beep)
        right_bottom.addWidget(self.cb_retest)
        right_bottom.addWidget(self.cb_autoclear)

        right_bottom.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_reset_pwd = QPushButton(" 密码重置 "); apply_button_types(btn_reset_pwd, "neutral")
        btn_defaults = QPushButton(" 默认值 "); apply_button_types(btn_defaults, "neutral")
        btn_layout.addWidget(btn_reset_pwd)
        btn_layout.addWidget(btn_defaults)
        right_bottom.addLayout(btn_layout)

        bottom_layout.addLayout(right_bottom)
        main_layout.addLayout(bottom_layout)
        self._load_params()

    # ---- 参数持久化 ----
    def _load_params(self):
        """从 SQLite 加载全部试验参数填充到控件"""
        p = load_params()
        # 化验员
        for i in range(6):
            v = p.get("tech_" + str(i), "")
            if v and i < len(self.tech_inputs):
                self.tech_inputs[i].setText(str(v))
        # 单位
        # 串口号
        port_val = p.get("com_port", "COM1")
        idx = self.cb_com_port.findText(port_val)
        if idx >= 0:
            self.cb_com_port.setCurrentIndex(idx)
        self.le_unit.setText(p.get("unit", ""))
        # 样位数量
        sc = p.get("sample_count", "")
        if sc: self.le_sample_count.setText(str(int(sc)))
        else: self.le_sample_count.clear()
        # 测试方法
        m = p.get("method", "gb")
        if m == "kf": self.rb_kf.setChecked(True)
        elif m == "custom": self.rb_custom.setChecked(True)
        else: self.rb_gb.setChecked(True)
        # 称重方式
        wi = p.get("weigh_mode", 0)
        if wi is not None:
            self.cb_weigh.setCurrentIndex(int(wi))
        # 分析水
        self._set_val("aw_temp", p, self.le_aw_temp)
        self._set_val("aw_time", p, self.le_aw_time)
        self.cb_aw_const.setChecked(bool(p.get("aw_const_check", 1)))
        self._set_val("aw_prec", p, self.le_aw_prec, "{:.4f}")
        self._set_val("aw_interval", p, self.le_aw_interval)
        self._set_val("aw_low", p, self.le_aw_low, "{:.4f}")
        self._set_val("aw_high", p, self.le_aw_high, "{:.4f}")
        self.cb_aw_fan.setChecked(bool(p.get("aw_fan", 0)))
        self._set_val("aw_corr", p, self.le_aw_corr, "{:.2f}")
        # 全水
        self._set_val("tw_temp", p, self.le_tw_temp)
        self._set_val("tw_time", p, self.le_tw_time)
        self.cb_tw_const.setChecked(bool(p.get("tw_const_check", 1)))
        self._set_val("tw_prec", p, self.le_tw_prec, "{:.4f}")
        self._set_val("tw_interval", p, self.le_tw_interval)
        self._set_val("tw_low", p, self.le_tw_low, "{:.4f}")
        self._set_val("tw_high", p, self.le_tw_high, "{:.4f}")
        self.cb_tw_fan.setChecked(bool(p.get("tw_fan", 1)))
        self._set_val("tw_corr", p, self.le_tw_corr, "{:.2f}")
        # 其他
        self.cb_beep.setChecked(bool(p.get("beep", 1)))
        self.cb_retest.setChecked(bool(p.get("retest", 0)))
        self.cb_autoclear.setChecked(bool(p.get("autoclear", 0)))

    @staticmethod
    def _set_val(key, params_dict, line_edit, fmt=None):
        """辅助方法：将数据库值填入 QLineEdit"""
        v = params_dict.get(key)
        if v is not None:
            if fmt:
                line_edit.setText(fmt.format(float(v)))
            else:
                line_edit.setText(str(int(v)) if isinstance(v, int) else str(v))

    def _save_tech(self, idx, text):
        """实时保存化验员名字到 SQLite"""
        save_tech(idx, text)


    def _save_com_port(self, port):
        """串口号改变时直接存入数据库"""
        from db import load_params, save_params
        p = load_params()
        p["com_port"] = port
        save_params(**p)
        print("[SETTINGS] 串口号已保存:", port)
    def save_all_params(self):
        """保存当前对话框所有参数到数据库（可在关闭前调用）"""
        import sys; print("[DEBUG] save_all_params called", file=sys.stderr)
        kwargs = {}
        for i in range(6):
            kwargs["tech_" + str(i)] = self.tech_inputs[i].text() if i < len(self.tech_inputs) else ""
        # 单位
        kwargs["unit"] = self.le_unit.text()
        # 样位数量（范围校验: 9~50，不在范围内不存入）
        try:
            v = int(self.le_sample_count.text().strip())
            if 9 <= v <= 50:
                kwargs["sample_count"] = v
        except (ValueError, TypeError):
            pass
        # 方法
        if self.rb_gb.isChecked(): kwargs["method"] = "gb"
        elif self.rb_kf.isChecked(): kwargs["method"] = "kf"
        else: kwargs["method"] = "custom"
        kwargs["weigh_mode"] = self.cb_weigh.currentIndex()
        # 分析水
        kwargs["aw_temp"] = float(self.le_aw_temp.text() or "0")
        kwargs["aw_time"] = int(self.le_aw_time.text() or "0")
        kwargs["aw_const_check"] = 1 if self.cb_aw_const.isChecked() else 0
        kwargs["aw_prec"] = float(self.le_aw_prec.text() or "0")
        kwargs["aw_interval"] = int(self.le_aw_interval.text() or "0")
        kwargs["aw_low"] = float(self.le_aw_low.text() or "0")
        kwargs["aw_high"] = float(self.le_aw_high.text() or "0")
        kwargs["aw_fan"] = 1 if self.cb_aw_fan.isChecked() else 0
        kwargs["aw_corr"] = float(self.le_aw_corr.text() or "0")
        # 全水
        kwargs["tw_temp"] = float(self.le_tw_temp.text() or "0")
        kwargs["tw_time"] = int(self.le_tw_time.text() or "0")
        kwargs["tw_const_check"] = 1 if self.cb_tw_const.isChecked() else 0
        kwargs["tw_prec"] = float(self.le_tw_prec.text() or "0")
        kwargs["tw_interval"] = int(self.le_tw_interval.text() or "0")
        kwargs["tw_low"] = float(self.le_tw_low.text() or "0")
        kwargs["tw_high"] = float(self.le_tw_high.text() or "0")
        kwargs["tw_fan"] = 1 if self.cb_tw_fan.isChecked() else 0
        kwargs["tw_corr"] = float(self.le_tw_corr.text() or "0")
        # 其他
        # 串口号
        kwargs["com_port"] = self.cb_com_port.currentText()
        kwargs["beep"] = 1 if self.cb_beep.isChecked() else 0
        kwargs["retest"] = 1 if self.cb_retest.isChecked() else 0
        kwargs["autoclear"] = 1 if self.cb_autoclear.isChecked() else 0
        save_params(**kwargs)

    def closeEvent(self, event):
        """关闭时自动保存所有参数"""
        self.save_all_params()
        super().closeEvent(event)
        self.params_changed.emit()  # 主界面异步刷新


# ============================================================
# 独立测试入口
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dlg = SettingsDialog()
    dlg.exec_()



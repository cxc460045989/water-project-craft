# -*- coding: utf-8 -*-
"""称量对话框 - 微机全自动水分测定仪
支持多状态: 倒计时/坩埚称量/放样提示/样品称量/完成收尾
"""

from PySide2.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
)
from PySide2.QtCore import Qt, Signal
from button_styles import apply_button_types


class WeighDialog(QDialog):
    """称量弹窗，状态机驱动显示不同界面内容"""
    start_sample_clicked = Signal()  # 用户点击「开始称量样品重量」
    start_sample_clicked = Signal()  # 用户点击「开始称量样品重量」
    confirm_weigh_clicked = Signal()  # 用户点击「确认称重」

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("称量提示")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(936, 462)
        self.setModal(True)
        self._build_ui()
        self._apply_style()
        self._phase = ""

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(48, 34, 48, 28)

        # ---- 第一行：状态/主标题 ----
        self.title_label = QLabel()
        self.title_label.setObjectName("weighTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addSpacing(18)

        # ---- 第二行：倒计时或样品名 ----
        self.sub_label = QLabel()
        self.sub_label.setObjectName("weighSub")
        self.sub_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.sub_label)
        layout.addSpacing(16)

        # ---- 第三行：重量/提示 ----
        self.weight_label = QLabel()
        self.weight_label.setObjectName("weighWeight")
        self.weight_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.weight_label)
        layout.addStretch()

        # ---- 底部按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(40)
        btn_layout.addStretch()

        self.btn_confirm = QPushButton("确认称重")
        apply_button_types(self.btn_confirm, "action")
        self.btn_confirm.clicked.connect(self._on_confirm_clicked)
        self.btn_confirm.setMinimumWidth(140)
        self.btn_confirm.setVisible(False)
        btn_layout.addWidget(self.btn_confirm)
        self.btn_action = QPushButton("开始称量样品重量")
        apply_button_types(self.btn_action, "action")
        self.btn_action.clicked.connect(self._on_action_clicked)
        self.btn_action.setMinimumWidth(180)
        self.btn_action.setVisible(False)
        btn_layout.addWidget(self.btn_action)

        self.btn_cancel = QPushButton("结束称量")
        apply_button_types(self.btn_cancel, "neutral")
        self.btn_cancel.setMinimumWidth(110)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #E8EBF0;
            }
            QLabel#weighTitle {
                font-size: 48px;
                font-weight: bold;
                color: #1F2937;
                background: transparent;
                font-family: "Courier New", "Consolas", monospace;
            }
            QLabel#weighSub {
                font-size: 48px;
                font-weight: bold;
                color: #0D47A1;
                background: transparent;
                font-family: "Courier New", "Consolas", monospace;
            }
            QLabel#weighWeight {
                font-size: 64px;
                font-weight: bold;
                color: #0D47A1;
                font-family: "Courier New", "Consolas", monospace;
                background: transparent;
                padding: 8px 0px;
            }
        """)
        from button_styles import BUTTON_QSS
        self.setStyleSheet(self.styleSheet() + BUTTON_QSS)

    def _on_action_clicked(self):
        self.start_sample_clicked.emit()

    def _on_confirm_clicked(self):
        """用户点击「确认称重」"""
        self.confirm_weigh_clicked.emit()


    # ---- 状态切换接口 ----

    def show_status(self, msg):
        """显示硬件动作状态提示"""
        self._phase = "status"
        self.btn_action.setVisible(False)
        self.btn_confirm.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(False)
        self.title_label.setText(msg)
        self.sub_label.setText("")
        self.weight_label.setText("")

    def show_weighing(self, row, name, weight):
        """正在称量坩埚重量"""
        self._phase = "weighing"
        self.btn_action.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(False)

        self.title_label.setText("正在称量 " + str(row + 1) + " 号坩埚")
        self.sub_label.setText("样品名称：" + name)
        self.weight_label.setText("{:.4f}g".format(weight))

    def show_weighing_sample(self, row, name, weight):
        """正在称量样品重量"""
        self._phase = "weighing_sample"
        self.btn_action.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(False)

        self.title_label.setText("正在称量 " + str(row + 1) + " 号样品")
        self.sub_label.setText("样品名称：" + name)
        self.weight_label.setText("{:.4f}g".format(weight))

    def show_add_sample_prompt(self):
        """放样提示界面"""
        self._phase = "add_sample"
        self.title_label.setText("请添加样品后开始称量样品重量")
        self.sub_label.setText("")
        self.weight_label.setText("")
        self.btn_action.setText("开始称量样品重量")
        self.btn_action.setVisible(True)
        self.btn_action.setEnabled(True)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)

    def show_finished(self):
        """流程完成，延迟关闭"""
        self._phase = "finished"
        self.title_label.setText("称量完成")
        self.sub_label.setText("")
        self.weight_label.setText("")
        self.btn_action.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(False)

    def enable_cancel(self, enabled):
        self.btn_cancel.setEnabled(enabled)


    def show_single_weigh_waiting(self, row, name, weight):
        """单个称量：等待确认状态，显示实时重量"""
        self._phase = "single_waiting"
        self.btn_action.setVisible(False)
        self.btn_confirm.setVisible(True)
        self.btn_confirm.setEnabled(True)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.title_label.setText("请添加样品后点击确认")
        self.sub_label.setText(str(row + 1) + "号 " + name)
        self.weight_label.setText("{:.4f}g".format(weight))

    def show_single_out_of_range(self, name, weight, lo, hi):
        """重量超限提示"""
        self._phase = "out_of_range"
        self.btn_confirm.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(False)
        self.title_label.setText("样品重量超出范围")
        self.sub_label.setText("样重超出范围（{:.4f}-{:.4f}g）！".format(lo, hi))
        self.weight_label.setText("将重新称量该样品")

    def update_real_time_weight(self, weight):
        """刷新实时重量显示"""
        if self._phase in ("single_waiting", "individual_waiting"):
            self.weight_label.setText("{:.4f}g".format(weight))

    def show_single_weigh_done(self, row, weight):
        """单个样品称量完成"""
        self._phase = "single_done"
        self.btn_confirm.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(False)
        self.title_label.setText(str(row + 1) + "号称量完成")
        self.sub_label.setText("重量: {:.4f}g".format(weight))
        self.weight_label.setText("")

    def show_individual_weighing(self, row, name, weight):
        """单独称重模式: 实时重量 + 确认按钮"""
        self._phase = "individual_waiting"
        self.btn_action.setVisible(False)
        self.btn_confirm.setVisible(True)
        self.btn_confirm.setEnabled(True)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.title_label.setText("正在称量 " + str(row + 1) + " 号样品")
        self.sub_label.setText("样品名称：" + name)
        self.weight_label.setText("{:.4f}g".format(weight))
    def reset(self):
        self.title_label.setText("")
        self.sub_label.setText("")
        self.btn_confirm.setVisible(False)
        self.btn_action.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._phase = ""
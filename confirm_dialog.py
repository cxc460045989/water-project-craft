# -*- coding: utf-8 -*-
"""通用确认对话框 - 微机全自动水分测定仪
用法:
    from confirm_dialog import ConfirmDialog
    if ConfirmDialog.confirm(self, "确定要删除当前数据吗？"):
        # 执行删除
"""

from PySide2.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSizePolicy,
)
from PySide2.QtCore import Qt
from PySide2.QtGui import QFont


class ConfirmDialog(QDialog):
    """通用确认对话框，纯文本/简约风格"""

    MSG_STYLE = """
        font-size: 15px;
        font-weight: bold;
        color: #1F2937;
        padding: 0 4px;
    """

    def __init__(self, parent, message, title="确认操作",
                 confirm_text="确定", cancel_text="取消",
                 danger=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )
        self.setFixedSize(420, 160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(0)

        # 消息
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(self.MSG_STYLE + "padding: 16px 4px;")
        msg_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(msg_label)

        layout.addStretch()

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton(cancel_text)
        btn_cancel.setStyleSheet(self._btn_style("neutral"))
        btn_cancel.setFixedSize(100, 34)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)

        btn_confirm = QPushButton(confirm_text)
        btn_type = "danger" if danger else "primary"
        btn_confirm.setStyleSheet(self._btn_style(btn_type))
        btn_confirm.setFixedSize(100, 34)
        btn_confirm.setDefault(True)
        btn_confirm.clicked.connect(self.accept)
        btn_layout.addWidget(btn_confirm)

        layout.addLayout(btn_layout)

    @staticmethod
    def _btn_style(btn_type):
        if btn_type == "primary":
            return """
                QPushButton {
                    background-color: #2B579A; color: #FFFFFF;
                    border: none; border-radius: 4px;
                    font-size: 13px; font-weight: bold;
                }
                QPushButton:hover { background-color: #1E3F73; }
                QPushButton:pressed { background-color: #152D52; }
            """
        elif btn_type == "danger":
            return """
                QPushButton {
                    background-color: #C62828; color: #FFFFFF;
                    border: none; border-radius: 4px;
                    font-size: 13px; font-weight: bold;
                }
                QPushButton:hover { background-color: #AD2222; }
                QPushButton:pressed { background-color: #941C1C; }
            """
        else:
            return """
                QPushButton {
                    background-color: #DDE1E8; color: #1F2937;
                    border: none; border-radius: 4px;
                    font-size: 13px; font-weight: bold;
                }
                QPushButton:hover { background-color: #B0B8C4; }
                QPushButton:pressed { background-color: #9CA3AF; }
            """

    @staticmethod
    def confirm(parent, message, title="确认操作",
                confirm_text="确定", cancel_text="取消",
                danger=False):
        """静态快捷方法，返回 True/False"""
        dlg = ConfirmDialog(parent, message, title,
                            confirm_text, cancel_text, danger)
        return dlg.exec_() == QDialog.Accepted


# ===== 独立测试 =====
if __name__ == "__main__":
    import sys
    from PySide2.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if ConfirmDialog.confirm(None, "确定要删除当前实验数据吗？\n此操作不可撤销！",
                             title="删除确认", danger=True):
        print("Confirmed")
    else:
        print("Cancelled")

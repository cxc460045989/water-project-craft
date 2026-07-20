# -*- coding: utf-8 -*-
"""密码对话框 — 微机全自动水分测定仪
提供:
  PasswordDialog.verify(parent, pwd_type)  → 单密码验证, 返回 True/False
  PasswordSettingsDialog.change(parent)     → 修改三种密码
"""

from PySide2.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)
from PySide2.QtCore import Qt, Signal
from db import load_passwords, save_password

PWD_LABELS = {
    "boot": "开机密码",
    "user": "用户密码",
    "admin": "管理员密码",
}


class PasswordDialog(QDialog):
    """密码验证对话框 — 输入单个密码进行验证"""

    def __init__(self, parent, pwd_type="boot"):
        """pwd_type: 'boot' | 'user' | 'admin'"""
        super().__init__(parent)
        self._pwd_type = pwd_type
        label_text = PWD_LABELS.get(pwd_type, "密码")

        self.setWindowTitle(label_text)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(360, 150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(0)

        title = QLabel("请输入%s" % label_text)
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1F2937;")
        layout.addWidget(title)
        layout.addSpacing(14)

        self._pwd_input = QLineEdit()
        self._pwd_input.setEchoMode(QLineEdit.Password)
        self._pwd_input.setPlaceholderText("请输入密码")
        self._pwd_input.setStyleSheet("""
            QLineEdit {
                font-size: 14px; padding: 6px 10px;
                border: 1px solid #B0B8C4; border-radius: 3px;
                background: #FFFFFF;
            }
        """)
        self._pwd_input.setFocus()
        self._pwd_input.returnPressed.connect(self._on_confirm)
        layout.addWidget(self._pwd_input)
        layout.addSpacing(14)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("font-size: 12px; color: #C62828;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 30)
        btn_cancel.setStyleSheet(self._btn_style("neutral"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.setFixedSize(80, 30)
        btn_ok.setStyleSheet(self._btn_style("primary"))
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._on_confirm)
        btn_layout.addWidget(btn_ok)

        layout.addStretch()
        layout.addLayout(btn_layout)

    def _on_confirm(self):
        pwd = self._pwd_input.text()
        passwords = load_passwords()
        expected = passwords.get(self._pwd_type, "1234")
        if pwd == expected:
            self.accept()
        else:
            self._error_label.setText("密码错误，请重新输入")
            self._error_label.setVisible(True)
            self._pwd_input.clear()
            self._pwd_input.setFocus()

    @staticmethod
    def verify(parent, pwd_type):
        """静态方法：验证指定类型密码，返回 True/False"""
        dlg = PasswordDialog(parent, pwd_type)
        return dlg.exec_() == QDialog.Accepted

    @staticmethod
    def _btn_style(btn_type):
        if btn_type == "primary":
            return """
                QPushButton {
                    background-color: #2B579A; color: #FFFFFF;
                    border: none; border-radius: 3px;
                    font-size: 13px; font-weight: bold;
                }
                QPushButton:hover { background-color: #1E3F73; }
                QPushButton:pressed { background-color: #152D52; }
            """
        else:
            return """
                QPushButton {
                    background-color: #DDE1E8; color: #1F2937;
                    border: none; border-radius: 3px;
                    font-size: 13px; font-weight: bold;
                }
                QPushButton:hover { background-color: #B0B8C4; }
                QPushButton:pressed { background-color: #9CA3AF; }
            """


class PasswordSettingsDialog(QDialog):
    """密码设置对话框 — 修改三种密码"""

    password_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("密码设置")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(380, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(0)

        title = QLabel("密码设置")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1F2937;")
        layout.addWidget(title)
        layout.addSpacing(16)

        passwords = load_passwords()

        widgets = []
        for key, label in [("boot", "开机密码"), ("user", "用户密码"), ("admin", "管理员密码")]:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setFixedWidth(70)
            lbl.setStyleSheet("font-size: 13px; color: #1F2937;")
            row.addWidget(lbl)

            le = QLineEdit()
            le.setText(passwords.get(key, "1234"))
            le.setStyleSheet("""
                QLineEdit {
                    font-size: 13px; padding: 4px 8px;
                    border: 1px solid #B0B8C4; border-radius: 3px;
                    background: #FFFFFF;
                }
            """)
            row.addWidget(le, 1)
            widgets.append(le)
            layout.addLayout(row)
            layout.addSpacing(8)

        self._inputs = {"boot": widgets[0], "user": widgets[1], "admin": widgets[2]}
        layout.addSpacing(8)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("font-size: 12px; color: #C62828;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 30)
        btn_cancel.setStyleSheet(PasswordDialog._btn_style("neutral"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton("保存")
        btn_save.setFixedSize(80, 30)
        btn_save.setStyleSheet(PasswordDialog._btn_style("primary"))
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _on_save(self):
        has_empty = False
        for key, le in self._inputs.items():
            pwd = le.text().strip()
            if not pwd:
                has_empty = True
                self._error_label.setText("密码不能为空")
                self._error_label.setVisible(True)
                return
            save_password(key, pwd)
        self._error_label.setVisible(False)
        self.password_changed.emit()
        self.accept()

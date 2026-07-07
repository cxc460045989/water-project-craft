# -*- coding: utf-8 -*-
"""按钮拟物立体样式 — QSS 实现
框架: PySide2 (Qt5) — 兼容 Windows 7 / 麒麟 Linux x86/ARM64
用法:
    from button_styles import BUTTON_QSS, apply_button_types
    app.setStyleSheet(app.styleSheet() + BUTTON_QSS)
    # 或在窗口 setStyleSheet 时拼接
    # 给按钮设置类型:  button.setProperty("btn-type", "danger")
    # 刷新样式:        button.style().unpolish(button); button.style().polish(button)

颜色体系（便于微调）:
  - 正向/主操作 (绿色):  正常 #2E7D32 → #1B5E20
  - 危险/停止 (红色):    正常 #C62828 → #AD2222
  - 操作按钮 (蓝色):     正常 #1565C0 → #0D47A1
  - 普通功能 (灰阶):     正常 #4B5563 → #374151
  - 默认 (灰白):         正常 #DDE1E8 → #B0B8C4
"""

BUTTON_QSS = """
/* ============================================================
   按钮拟物立体样式 — btn-type 属性选择器方案
   兼容 PySide2 (Qt5) 所有版本，仅使用标准 QSS 属性
   ============================================================ */

/* ---------- 全局默认按钮（不设 btn-type 的普通灰白按钮） ---------- */
QPushButton {
    /* 凸起立体 — 正常态 */
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #F2F4F7, stop:0.4 #E2E6ED, stop:1 #CBD0DA);
    color: #1F2937;
    border: 1px solid #B0B8C4;
    border-top-color: #D1D5DB;
    border-left-color: #D1D5DB;
    border-bottom-color: #9098A4;
    border-right-color: #9098A4;
    border-radius: 5px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: bold;
    min-height: 28px;
}
QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #F9FAFB, stop:0.4 #E9EDF3, stop:1 #D2D8E2);
    border-top-color: #BCC3CE;
    border-left-color: #BCC3CE;
    border-bottom-color: #808A96;
    border-right-color: #808A96;
}
QPushButton:pressed {
    /* 凹陷效果 — 渐变反转 + 边框光影反转 + 内容下移 */
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #BCC3CE, stop:0.6 #D5DAE2, stop:1 #E2E6ED);
    border-top-color: #808A96;
    border-left-color: #808A96;
    border-bottom-color: #D1D5DB;
    border-right-color: #D1D5DB;
    padding-top: 7px;
    padding-bottom: 5px;
    padding-left: 16px;
    padding-right: 16px;
}
QPushButton:disabled {
    background-color: #E8EBF0;
    color: #9CA3AF;
    border: 1px solid #D1D5DB;
    border-top-color: #D1D5DB;
    border-left-color: #D1D5DB;
    border-bottom-color: #C8CED8;
    border-right-color: #C8CED8;
}

/* ============================================================
   正向主按钮 — btn-type="primary"
   绿色体系：开始测试 / 启动操作
   ============================================================ */
QPushButton[btn-type="primary"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #43A047, stop:0.4 #388E3C, stop:1 #2E7D32);
    color: #FFFFFF;
    border: 1px solid #1B5E20;
    border-top-color: #4CAF50;
    border-left-color: #4CAF50;
    border-bottom-color: #1B5E20;
    border-right-color: #1B5E20;
    border-radius: 5px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: bold;
    min-height: 28px;
}
QPushButton[btn-type="primary"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4CAF50, stop:0.4 #43A047, stop:1 #388E3C);
    border-top-color: #66BB6A;
    border-left-color: #66BB6A;
    border-bottom-color: #14521A;
    border-right-color: #14521A;
}
QPushButton[btn-type="primary"]:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1B5E20, stop:0.6 #2E7D32, stop:1 #388E3C);
    border-top-color: #14521A;
    border-left-color: #14521A;
    border-bottom-color: #4CAF50;
    border-right-color: #4CAF50;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton[btn-type="primary"]:disabled {
    background-color: #A5C8A7;
    color: #E0E8E0;
    border: 1px solid #8BB88E;
    border-top-color: #8BB88E;
    border-left-color: #8BB88E;
    border-bottom-color: #7AAB7D;
    border-right-color: #7AAB7D;
}

/* ============================================================
   危险/停止按钮 — btn-type="danger"
   红色体系：停止测试 / 退出程序
   ============================================================ */
QPushButton[btn-type="danger"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #EF5350, stop:0.4 #E53935, stop:1 #C62828);
    color: #FFFFFF;
    border: 1px solid #B71C1C;
    border-top-color: #EF5350;
    border-left-color: #EF5350;
    border-bottom-color: #B71C1C;
    border-right-color: #B71C1C;
    border-radius: 5px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: bold;
    min-height: 28px;
}
QPushButton[btn-type="danger"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #EF5350, stop:0.4 #EF5350, stop:1 #E53935);
    border-top-color: #FF7043;
    border-left-color: #FF7043;
    border-bottom-color: #941C1C;
    border-right-color: #941C1C;
}
QPushButton[btn-type="danger"]:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #B71C1C, stop:0.6 #C62828, stop:1 #E53935);
    border-top-color: #941C1C;
    border-left-color: #941C1C;
    border-bottom-color: #EF5350;
    border-right-color: #EF5350;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton[btn-type="danger"]:disabled {
    background-color: #C88A8A;
    color: #F0E0E0;
    border: 1px solid #B87A7A;
    border-top-color: #B87A7A;
    border-left-color: #B87A7A;
    border-bottom-color: #A86A6A;
    border-right-color: #A86A6A;
}

/* ============================================================
   操作按钮 — btn-type="action"
   蓝色体系：称量样重 / 追加样品 / 链接测试 / 上传数据
   ============================================================ */
QPushButton[btn-type="action"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #42A5F5, stop:0.4 #1E88E5, stop:1 #1565C0);
    color: #FFFFFF;
    border: 1px solid #0D47A1;
    border-top-color: #64B5F6;
    border-left-color: #64B5F6;
    border-bottom-color: #0D47A1;
    border-right-color: #0D47A1;
    border-radius: 5px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: bold;
    min-height: 28px;
}
QPushButton[btn-type="action"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #64B5F6, stop:0.4 #42A5F5, stop:1 #1E88E5);
    border-top-color: #90CAF9;
    border-left-color: #90CAF9;
    border-bottom-color: #0A3A7A;
    border-right-color: #0A3A7A;
}
QPushButton[btn-type="action"]:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0D47A1, stop:0.6 #1565C0, stop:1 #1E88E5);
    border-top-color: #0A3A7A;
    border-left-color: #0A3A7A;
    border-bottom-color: #64B5F6;
    border-right-color: #64B5F6;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton[btn-type="action"]:disabled {
    background-color: #8BB8D8;
    color: #E0EAF0;
    border: 1px solid #7AA8C8;
    border-top-color: #7AA8C8;
    border-left-color: #7AA8C8;
    border-bottom-color: #6A98B8;
    border-right-color: #6A98B8;
}

/* ============================================================
   普通功能按钮 — btn-type="neutral"
   灰阶体系：顶部工具栏 / 弹窗内功能按钮 / 样盘控制 / 密码重置等
   ============================================================ */
QPushButton[btn-type="neutral"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #6B7280, stop:0.4 #4B5563, stop:1 #374151);
    color: #FFFFFF;
    border: 1px solid #1F2937;
    border-top-color: #9CA3AF;
    border-left-color: #9CA3AF;
    border-bottom-color: #1F2937;
    border-right-color: #1F2937;
    border-radius: 5px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: bold;
    min-height: 28px;
}
QPushButton[btn-type="neutral"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #9CA3AF, stop:0.4 #6B7280, stop:1 #4B5563);
    border-top-color: #B0B8C4;
    border-left-color: #B0B8C4;
    border-bottom-color: #111827;
    border-right-color: #111827;
}
QPushButton[btn-type="neutral"]:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1F2937, stop:0.6 #374151, stop:1 #4B5563);
    border-top-color: #111827;
    border-left-color: #111827;
    border-bottom-color: #9CA3AF;
    border-right-color: #9CA3AF;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton[btn-type="neutral"]:disabled {
    background-color: #9CA3AF;
    color: #D1D5DB;
    border: 1px solid #8B919E;
    border-top-color: #8B919E;
    border-left-color: #8B919E;
    border-bottom-color: #7B818E;
    border-right-color: #7B818E;
}

/* ============================================================
   工具栏按钮（#toolButton）— 保持扁平但融入立体感
   ============================================================ */
#toolButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #FFFFFF, stop:0.5 #F9FAFB, stop:1 #F0F2F5);
    color: #1F2937;
    border: 1px solid #D1D5DB;
    border-top-color: #E5E7EB;
    border-left-color: #E5E7EB;
    border-bottom-color: #B0B8C4;
    border-right-color: #B0B8C4;
    border-radius: 4px;
    padding: 4px 2px;
    text-align: center;
    font-size: 13px;
    min-height: 36px;
}
#toolButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #F9FAFB, stop:0.5 #EBF0F8, stop:1 #E2E6ED);
    color: #2B579A;
    border-color: #2B579A;
}
#toolButton:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #DCE3EF, stop:0.5 #E5EAF3, stop:1 #EBF0F8);
    border-top-color: #9098A4;
    border-left-color: #9098A4;
    border-bottom-color: #D1D5DB;
    border-right-color: #D1D5DB;
    padding-top: 5px;
    padding-bottom: 3px;
}
"""


def apply_button_types(button, btn_type):
    """给按钮设置 btn-type 属性并刷新样式。
    
    参数:
        button: QPushButton 实例
        btn_type: "primary" | "danger" | "action" | "neutral" | None
                  传 None 恢复默认灰白样式
    用法:
        apply_button_types(my_btn, "primary")
        # 等效于:
        # my_btn.setProperty("btn-type", "primary")
        # my_btn.style().unpolish(my_btn)
        # my_btn.style().polish(my_btn)
    """
    if btn_type is None:
        button.setProperty("btn-type", None)
    else:
        button.setProperty("btn-type", btn_type)
    # 刷新样式使其立即生效
    s = button.style()
    if s:
        s.unpolish(button)
        s.polish(button)


# -*- coding: utf-8 -*-
"""统一日志模块 - 微机全自动水分测定仪
日志分级写入 logs/ 目录 + 控制台输出
- 按日期分文件: logs/YYYYMMDD.log
- 同一天多次启动: 同一文件追加, 写入会话分割线
- 跨天自动切换新文件
使用:
  from logging_util import logger
  logger.info("[SERIAL] 串口已连接")
  logger.debug("[DB-CELL] cell changed")
  logger.error("[SERIAL] 连接失败")
"""
import os, sys, datetime

if getattr(sys, "frozen", False):
    _base = os.path.dirname(os.path.abspath(sys.argv[0]))
else:
    _base = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_base, "logs")

_FILE_TAGS = frozenset([
    "[SERIAL]", "[WEIGH]", "[HARDWARE]",
    "[DB]", "[DB-CELL]", "[TABLE]", "[RESTORE]",
    "[APPEND]", "[APPEND-V2]", "[CMD]",
    "[BATCH_WEIGH]", "[CONST_WEIGHT]",
    "[TEMP_CTRL]", "[PROCESS]",
    "[QUERY]", "[PRINT]",
    "[TEST]",
])

def _ensure_log_dir():
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception:
        pass

def _today_str():
    return datetime.date.today().strftime("%Y%m%d")

def _now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _get_log_path():
    return os.path.join(_LOG_DIR, _today_str() + ".log")

_SEPARATOR = "=" * 60 + "\n=== 新会话开始: {ts} ===\n" + "=" * 60 + "\n"

class Logger:
    def __init__(self):
        self._current_date = None  # 当前写入的日志文件日期
        _ensure_log_dir()
        self._write_session_separator()

    def _write_session_separator(self):
        """启动时: 如当天日志文件已有内容则写入分割线, 标记新会话"""
        log_path = _get_log_path()
        try:
            if os.path.isfile(log_path) and os.path.getsize(log_path) > 0:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n" + _SEPARATOR.format(ts=_now_str()) + "\n")
            self._current_date = _today_str()
        except Exception:
            pass

    def info(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = ts + " " + msg
        print(line)
        self._write_file(line)

    def warning(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = ts + " [WARN] " + msg
        print(line)
        self._write_file(line)

    def error(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = ts + " [ERROR] " + msg
        print(line)
        self._write_file(line)

    def debug(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = ts + " " + msg
        print(line)

    def _write_file(self, line):
        for tag in _FILE_TAGS:
            if tag in line:
                self._append_file(line)
                return

    def _append_file(self, line):
        try:
            _ensure_log_dir()
            today = _today_str()
            # 跨天检测: 日期变了则切新文件并写分割线
            if self._current_date is not None and self._current_date != today:
                log_path = os.path.join(_LOG_DIR, self._current_date + ".log")
                # 旧文件末尾写结束标记(尝试, 失败忽略)
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write("=== 会话结束: " + _now_str() + " ===\n")
                except Exception:
                    pass
                # 新文件写分割线
                new_path = _get_log_path()
                try:
                    with open(new_path, "a", encoding="utf-8") as f:
                        f.write("\n" + _SEPARATOR.format(ts=_now_str()) + "\n")
                except Exception:
                    pass
                self._current_date = today

            log_path = _get_log_path()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

logger = Logger()

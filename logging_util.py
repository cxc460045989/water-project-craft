# -*- coding: utf-8 -*-
"""统一日志模块 - 微机全自动水分测定仪
日志分级写入 logs/ 目录 + 控制台输出
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
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")
_MAX_BYTES = 5 * 1024 * 1024

_FILE_TAGS = frozenset([
    "[SERIAL]", "[WEIGH]", "[HARDWARE]", "[UPLINK]",
    "[DB-WEIGH]", "[DB]", "[MAIN]", "[SETTINGS]",
])

def _ensure_log_dir():
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception:
        pass

def _rotate_if_needed():
    try:
        if os.path.isfile(_LOG_FILE) and os.path.getsize(_LOG_FILE) > _MAX_BYTES:
            bak = _LOG_FILE + ".1"
            if os.path.isfile(bak): os.remove(bak)
            os.rename(_LOG_FILE, bak)
    except Exception:
        pass

class Logger:
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
            _rotate_if_needed()
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

logger = Logger()
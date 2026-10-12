"""轻量日志: 滚动文件 + 控制台, 供所有模块共用。

默认 INFO; 设环境变量 MCHOSE_DEBUG=1 开启 DEBUG。
文件位于 %LOCALAPPDATA%\\MCHOSEBattery\\logs\\, 单文件 1MB, 保留 2 个备份。
"""
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MCHOSEBattery", "logs")
_configured = False
_lock = threading.Lock()


def get_logger(name):
    global _configured
    # 独立的应用父 logger，所有模块向它传播，避免重复写入及第三方日志混入。
    with _lock:
        if not _configured:
            parent = logging.getLogger("mchoose")
            parent.propagate = False
            parent.setLevel(logging.DEBUG if os.environ.get("MCHOSE_DEBUG") else logging.INFO)
            fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                                    "%m-%d %H:%M:%S")
            try:
                os.makedirs(_DIR, exist_ok=True)
                fh = RotatingFileHandler(os.path.join(_DIR, "app.log"),
                                         maxBytes=1_000_000, backupCount=2, encoding="utf-8")
                fh.setFormatter(fmt)
                parent.addHandler(fh)
            except OSError:
                parent.addHandler(logging.NullHandler())
            if os.environ.get("MCHOSE_DEBUG") and sys.stderr is not None:
                sh = logging.StreamHandler(sys.stderr)
                sh.setFormatter(fmt)
                parent.addHandler(sh)
            _configured = True
    return logging.getLogger("mchoose." + name)

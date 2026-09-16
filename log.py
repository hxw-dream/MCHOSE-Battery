"""轻量日志: 滚动文件 + 控制台, 供所有模块共用。

默认 INFO; 设环境变量 MCHOSE_DEBUG=1 开启 DEBUG。
文件位于 %LOCALAPPDATA%\\MCHOSEBattery\\logs\\, 单文件 1MB, 保留 2 个备份。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MCHOSEBattery", "logs")
_configured = False


def get_logger(name):
    global _configured
    logger = logging.getLogger(name)
    if _configured:
        return logger
    _configured = True
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                            "%m-%d %H:%M:%S")
    try:
        os.makedirs(_DIR, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(_DIR, "app.log"),
                                 maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    if os.environ.get("MCHOSE_DEBUG"):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    else:
        logger.setLevel(logging.INFO)
    return logger

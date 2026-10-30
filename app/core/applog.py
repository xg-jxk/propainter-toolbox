# -*- coding: utf-8 -*-
"""应用日志：滚写入 %LOCALAPPDATA%\\ProPainterToolbox\\logs\\app.log。"""
import logging
import os
from logging.handlers import RotatingFileHandler

_LOGGER_NAME = "protoolbox"
_MAX_BYTES = 1024 * 1024
_BACKUPS = 4


def log_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ProPainterToolbox", "logs")


def setup(directory=None):
    """初始化日志；重复调用直接复用。返回日志文件路径（失败返回 None）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_protoolbox_ready", False):
        return logger.handlers[0].baseFilename if logger.handlers else None
    directory = directory or log_dir()
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "app.log")
        handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES,
                                      backupCount=_BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger._protoolbox_ready = True
        return path
    except OSError:
        return None


def write(text):
    """把一行界面日志同时落到文件。"""
    if not text:
        return
    logger = logging.getLogger(_LOGGER_NAME)
    if not getattr(logger, "_protoolbox_ready", False):
        return
    for line in str(text).splitlines():
        if line.strip():
            logger.info(line)

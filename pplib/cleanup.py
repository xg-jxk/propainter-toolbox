# -*- coding: utf-8 -*-
"""清理异常退出留下的临时文件。"""
import os
import shutil
import tempfile
import time

#: 我们会自己创建的临时前缀
PREFIXES = ("ppwm_", "ppsr_", "ppline_", "ppclip_", "ppjob_", "ppcmd_")


def _is_ours(name):
    return any(name.startswith(p) for p in PREFIXES)


def _dir_size(path):
    total = 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def scan(root=None):
    """列出可以清理的残留：[(path, size, mtime)]。"""
    root = root or tempfile.gettempdir()
    found = []
    try:
        names = os.listdir(root)
    except OSError:
        return found
    for name in names:
        if not _is_ours(name):
            continue
        path = os.path.join(root, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        found.append((path, _dir_size(path), mtime))
    return found


def sweep(max_age_hours=24, root=None):
    """删掉超过 max_age_hours 的残留；max_age_hours<=0 表示全部删。

    返回 (删除个数, 释放字节数)。
    """
    root = root or tempfile.gettempdir()
    now = time.time()
    limit = max_age_hours * 3600
    count = 0
    freed = 0
    for path, size, mtime in scan(root):
        if max_age_hours > 0 and now - mtime < limit:
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=False)
            else:
                os.remove(path)
            count += 1
            freed += size
        except OSError:
            continue
    return count, freed


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n

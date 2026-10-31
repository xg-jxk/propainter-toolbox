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


def _roots(root=None):
    if root:
        return [root]
    roots = []
    try:
        from .const import temp_root
        roots.append(temp_root())
    except Exception:
        pass
    sys_tmp = tempfile.gettempdir()
    if sys_tmp not in roots:
        roots.append(sys_tmp)
    return roots


def scan(root=None):
    """列出可以清理的残留：[(path, size, mtime)]。"""
    found = []
    for root in _roots(root):
        found.extend(_scan_one(root))
    return found


def _scan_one(root):
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

    注意：root=None 时必须和 scan() 用同一组目录（应用 temp + 系统 temp），
    否则会出现"弹窗说有 N 个残留，确定后却清理了 0 个"。
    """
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

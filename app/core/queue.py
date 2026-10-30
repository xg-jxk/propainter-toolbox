# -*- coding: utf-8 -*-
"""待处理队列（纯逻辑，不依赖 Qt，便于单测）。"""
import os
from dataclasses import dataclass, field
from typing import List

from pplib.const import MAX_QUEUE, normalize_inputs

STATUS_PENDING = "等待"
STATUS_RUNNING = "处理中"
STATUS_DONE = "完成"
STATUS_FAILED = "失败"
STATUS_CANCELLED = "已取消"
STATUS_SKIPPED = "跳过"


@dataclass
class QueueItem:
    path: str
    status: str = STATUS_PENDING
    out: str = ""
    pct: float = 0.0
    elapsed: float = 0.0
    message: str = ""

    @property
    def name(self):
        return os.path.basename(self.path)


class JobQueue(object):
    def __init__(self, limit=MAX_QUEUE):
        self.limit = int(limit)
        self._items = []

    # ---------------------------------------------------------- 查询
    def __len__(self):
        return len(self._items)

    def items(self):
        return list(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, idx):
        return self._items[idx]

    @property
    def full(self):
        return len(self._items) >= self.limit

    def next_pending_index(self):
        for i, it in enumerate(self._items):
            if it.status == STATUS_PENDING:
                return i
        return None

    # ---------------------------------------------------------- 修改
    def add_paths(self, paths):
        """返回 (added_items, rejected[(path, reason)])。"""
        accepted, rejected = normalize_inputs(paths, limit=self.limit - len(self._items))
        added = []
        for p in accepted:
            if any(os.path.normcase(i.path) == os.path.normcase(p) for i in self._items):
                continue
            item = QueueItem(path=p)
            self._items.append(item)
            added.append(item)
        if self.full:
            rejected = list(rejected)
        return added, rejected

    def remove(self, idx):
        if 0 <= idx < len(self._items):
            return self._items.pop(idx)
        return None

    def clear(self):
        self._items = []

    def reset(self):
        """开始新一轮队列前把状态清回等待。"""
        for it in self._items:
            it.status = STATUS_PENDING
            it.out = ""
            it.pct = 0.0
            it.elapsed = 0.0
            it.message = ""

    def find(self, path):
        for it in self._items:
            if os.path.normcase(it.path) == os.path.normcase(path):
                return it
        return None

# -*- coding: utf-8 -*-
"""PyInstaller 入口：把 app.main 包成带界面的 exe。

打包后 exe 与 tools/、pplib/、weights/ 在同一目录树里，
这里负责把 PP_ROOT 指到那个目录（最多向上找三层）。
"""
import os
import sys


def _score(path):
    """目录里运行时要素越多，越像"项目根"。"""
    score = 0
    if os.path.isdir(os.path.join(path, ".venv")):
        score += 4
    if os.path.isdir(os.path.join(path, "tools")):
        score += 2
    if os.path.isdir(os.path.join(path, "weights")):
        score += 1
    return score


def _find_root():
    """找项目根：优先 PP_ROOT，其次向上最多三层里"最像项目根"的那个。

    这样 dist\\ProPainterToolbox\\ProPainterToolbox.exe 也能直接用仓库根目录的
    .venv / weights（开发态），装到 %LOCALAPPDATA% 后又不会跑偏。
    """
    env = os.environ.get("PP_ROOT")
    if env and os.path.isdir(env):
        return env
    if getattr(sys, "frozen", False):
        start = os.path.dirname(os.path.abspath(sys.executable))
    else:
        start = os.path.dirname(os.path.abspath(__file__))

    best, best_score = start, -1
    d = start
    for _ in range(3):
        score = _score(d)
        if score > best_score:
            best, best_score = d, score
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return best


def main():
    root = _find_root()
    os.environ.setdefault("PP_ROOT", root)
    if root not in sys.path:
        sys.path.insert(0, root)
    from app.main import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())

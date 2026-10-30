# -*- coding: utf-8 -*-
"""PyInstaller 入口：把 app.main 包成带界面的 exe。

打包后 exe 与 tools/、pplib/、weights/ 在同一目录树里，
这里负责把 PP_ROOT 指到那个目录（最多向上找三层）。
"""
import os
import sys


def _find_root():
    env = os.environ.get("PP_ROOT")
    if env and os.path.isdir(os.path.join(env, "tools")):
        return env
    if getattr(sys, "frozen", False):
        start = os.path.dirname(os.path.abspath(sys.executable))
    else:
        start = os.path.dirname(os.path.abspath(__file__))
    d = start
    for _ in range(3):
        if os.path.isdir(os.path.join(d, "tools")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return start


def main():
    root = _find_root()
    os.environ.setdefault("PP_ROOT", root)
    if root not in sys.path:
        sys.path.insert(0, root)
    from app.main import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())

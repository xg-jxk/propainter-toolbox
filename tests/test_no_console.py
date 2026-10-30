# -*- coding: utf-8 -*-
"""防回退：GUI 里任何子进程都必须带 creationflags，否则会弹控制台黑窗。

Python 侧没有可靠的运行时手段检测"是否创建了控制台窗口"，所以在源码层面用 AST 检查：
pplib/ 与 app/ 下所有 subprocess.run/Popen/call/check_output 调用，必须显式传
creationflags，或者通过 **kwargs 转发给 winproc 的封装。
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SPAWN_FUNCS = {"run", "Popen", "call", "check_output", "check_call"}
#: 这些文件自己就是封装层，允许用 **kwargs 把 creationflags 透传进去
WHITELIST = {"pplib/winproc.py"}


def _scan(path):
    problems = []
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            continue
        if func.value.id != "subprocess" or func.attr not in SPAWN_FUNCS:
            continue
        names = {kw.arg for kw in node.keywords}
        splat = any(kw.arg is None for kw in node.keywords)
        if "creationflags" in names or (splat and rel in WHITELIST):
            continue
        if splat:
            continue        # **kwargs 透传（winproc 封装），运行时由封装补 flags
        problems.append("%s:%d subprocess.%s 没有 creationflags" % (rel, node.lineno, func.attr))
    return problems


class NoConsoleSpawnTest(unittest.TestCase):
    def test_no_subprocess_without_creationflags(self):
        problems = []
        for base in ("pplib", "app"):
            for dirpath, _dirs, files in os.walk(os.path.join(ROOT, base)):
                for name in files:
                    if name.endswith(".py"):
                        problems += _scan(os.path.join(dirpath, name))
        self.assertEqual(problems, [], "这些调用会弹控制台窗口：\n" + "\n".join(problems))

    def test_winproc_sets_flags(self):
        from pplib import winproc
        if os.name == "nt":
            self.assertEqual(winproc.NO_WINDOW, 0x08000000)
            self.assertEqual(winproc.extra_kwargs().get("creationflags"), 0x08000000)
        else:
            self.assertEqual(winproc.extra_kwargs(), {})

    def test_winproc_run_works(self):
        from pplib import winproc
        out = winproc.run([sys.executable, "-c", "print('ok')"],
                          stdout=-1, text=True)
        self.assertEqual(out.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()

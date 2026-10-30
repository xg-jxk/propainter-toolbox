# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：只打包 GUI 外壳，不打包 torch/cv2（运行时仍走 .venv）。

构建：
    .venv\\Scripts\\python.exe -m PyInstaller build\\app.spec --noconfirm --clean
"""
import os

ROOT = os.path.abspath(os.path.join(os.getcwd()))

a = Analysis(
    [os.path.join(ROOT, "build", "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "app", "resources"), os.path.join("app", "resources"))],
    hiddenimports=[
        "app.ui.mainwindow",
        "app.ui.install_dialog",
        "app.core.bridge",
        "app.core.queue",
        "app.core.config",
        "app.core.envcheck",
        "pplib.const",
        "pplib.options",
        "pplib.events",
        "pplib.ffmpeg",
    ],
    hookspath=[],
    runtime_hooks=[],
    # GUI 不需要科学计算栈；排除掉能让产物从 ~600MB 降到 ~80MB
    excludes=[
        "numpy", "scipy", "cv2", "torch", "torchvision", "matplotlib",
        "pandas", "PIL", "imageio", "imageio_ffmpeg", "timm", "skimage",
        "tkinter", "test", "pydoc_data",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ProPainterToolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "app", "resources", "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ProPainterToolbox",
)

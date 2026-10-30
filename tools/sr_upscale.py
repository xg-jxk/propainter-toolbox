# -*- coding: utf-8 -*-
"""Real-CUGAN 超分命令行（真正的逻辑在 pplib.sr）。

  python tools\\sr_upscale.py --video "D:\\v\\a.mp4"              # 2x
  python tools\\sr_upscale.py --video "D:\\v\\a.mp4" --scale 3 --denoise 3
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import Cancelled, JobError, cli_emitter  # noqa: E402
from pplib.options import SROptions  # noqa: E402
from pplib.sr import run_sr  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(description="Real-CUGAN 视频超分")
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3],
                    help="-1 不降噪，0 保守，1~3 递增强度；不给则按高度自动")
    ap.add_argument("--model", default="models-pro")
    ap.add_argument("--out", help="输出路径（默认源目录 <名字>_2x.mp4）")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--preset", default=None, help="x264 预设，默认 medium")
    ap.add_argument("--keep", action="store_true", help="保留中间文件")
    ap.add_argument("--log-file", dest="log_file")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    opts = SROptions(scale=a.scale, denoise=a.denoise, model=a.model,
                     crf=a.crf, encoder=a.encoder, preset=a.preset, keep=a.keep)
    emit = cli_emitter(a.log_file)
    try:
        run_sr(a.video, opts, emit, out=a.out)
        return 0
    except Cancelled:
        emit.cancelled_event()
        return 3
    except JobError as e:
        emit.error(str(e), e.hint)
        return 1


if __name__ == "__main__":
    sys.exit(main())

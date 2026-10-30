# -*- coding: utf-8 -*-
"""去水印 + 超分 一条龙命令行（逻辑在 pplib.job）。

  python tools\\pipeline.py --video "D:\\v\\a.mp4"                # 去水印 -> 2x
  python tools\\pipeline.py --video "D:\\v\\a.mp4" --scale 3 --rect 1314,918,320,120
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import Cancelled, JobError, cli_emitter  # noqa: E402
from pplib.job import run_job  # noqa: E402
from pplib.options import JobSpec, SROptions, WMOptions  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(description="去水印 + 超分 一条龙")
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--rect", help="水印矩形 x,y,w,h；不给就自动检测")
    ap.add_argument("--mask", help="掩码文件或掩码目录")
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3])
    ap.add_argument("--out")
    ap.add_argument("--padding", type=float, default=0.45)
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--intermediate-crf", type=int, default=12, dest="intermediate_crf",
                    help="去水印中间文件码率（默认 12；0 为无损但文件巨大）")
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--log-file", dest="log_file")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    spec = JobSpec(
        mode="pipeline",
        video=a.video,
        out=a.out,
        log_file=a.log_file,
        intermediate_crf=a.intermediate_crf,
        wm=WMOptions(auto=True, rect=a.rect, mask=a.mask, padding=a.padding,
                     crf=a.crf, encoder=a.encoder, keep=a.keep),
        sr=SROptions(scale=a.scale, denoise=a.denoise, crf=a.crf,
                     encoder=a.encoder, keep=a.keep),
    )
    emit = cli_emitter(a.log_file)
    try:
        run_job(spec, emit)
        return 0
    except Cancelled:
        emit.cancelled_event()
        return 3
    except JobError as e:
        emit.error(str(e), e.hint)
        return 1


if __name__ == "__main__":
    sys.exit(main())

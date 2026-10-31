# -*- coding: utf-8 -*-
"""区域修复 + 超分 一条龙命令行（逻辑在 pplib.job）。

  python tools\\pipeline.py --video "D:\\v\\a.mp4"                # 区域修复 -> 2x
  python tools\\pipeline.py --video "D:\\v\\a.mp4" --scale 3 --rect 1314,918,320,120
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import Cancelled, JobError, cli_emitter  # noqa: E402
from pplib.job import run_job  # noqa: E402
from pplib.options import JobSpec, SROptions, RepairOptions  # noqa: E402

#: --target 档位 -> 输出长边
TARGET_LONG = {"1080p": 1920, "2K": 2560, "4K": 3840, "8K": 7680}


def build_parser():
    ap = argparse.ArgumentParser(description="区域修复 + 超分 一条龙")
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4],
                    help="整数倍放大；给了 --target 就忽略它")
    ap.add_argument("--rect", help="目标区域矩形 x,y,w,h；不给就自动定位")
    ap.add_argument("--mask", help="掩码文件或掩码目录")
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3])
    ap.add_argument("--out")
    ap.add_argument("--padding", type=float, default=0.45)
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--intermediate-crf", type=int, default=12, dest="intermediate_crf",
                    help="区域修复中间文件码率（默认 12；0 为无损但文件巨大）")
    ap.add_argument("--target", default=None, choices=["1080p", "2K", "4K", "8K"],
                    help="统一输出长边（推荐）：小图超分到目标、大图只缩小")
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--no-cap", action="store_true", dest="no_cap",
                    help="不按分辨率封顶码率（4x/8K 时文件会大很多）")
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
        wm=RepairOptions(auto=True, rect=a.rect, mask=a.mask, padding=a.padding,
                     crf=a.crf, encoder=a.encoder, keep=a.keep,
                     cap_size=not a.no_cap),
        sr=SROptions(scale=a.scale, target_long=TARGET_LONG.get(a.target, 0),
                     denoise=a.denoise, crf=a.crf,
                     encoder=a.encoder, keep=a.keep, cap_size=not a.no_cap),
    )
    emit = cli_emitter(a.log_file)
    emit.log("提示：仅限处理你拥有版权或已获授权的视频（见 TERMS.md）")
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

# -*- coding: utf-8 -*-
"""去水印命令行（真正的逻辑在 pplib.wm，GUI 与 CLI 共用同一套流程）。

  python tools\\wm_remove.py --video "D:\\v\\a.mp4"                    # 自动检测
  python tools\\wm_remove.py --video "D:\\v\\a.mp4" --rect 1314,918,320,120
  python tools\\wm_remove.py --video "D:\\v\\a.mp4" --mask "D:\\v\\masks"
  python tools\\wm_remove.py --video "D:\\v\\a.mp4" --auto --dry-run    # 只看检测
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import Cancelled, JobError, cli_emitter  # noqa: E402
from pplib.options import WMOptions  # noqa: E402
from pplib.wm import run_wm  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(description="ProPainter 去水印")
    ap.add_argument("--video", required=True)
    ap.add_argument("--auto", action="store_true", help="自动检测水印位置（默认）")
    ap.add_argument("--rect", help="手动矩形 x,y,w,h")
    ap.add_argument("--mask", help="掩码文件或掩码目录")
    ap.add_argument("--out", help="输出路径（默认源目录 <名字>_无水印.mp4）")
    ap.add_argument("--padding", type=float, default=0.45, help="水印框外扩比例")
    ap.add_argument("--subvideo", type=int, default=40, help="长视频分段长度")
    ap.add_argument("--neighbor", type=int, default=10, help="局部邻域帧数")
    ap.add_argument("--ref-stride", type=int, default=12, dest="ref_stride")
    ap.add_argument("--mask-dilation", type=int, default=2, dest="mask_dilation")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--preset", default=None, help="x264 预设，默认 slow")
    ap.add_argument("--detect-thr", type=float, default=0.62, dest="detect_thr")
    ap.add_argument("--detect-fill", type=float, default=None, dest="detect_fill",
                    help="白色填充率上限，默认 0.60；文字水印偏密可试 0.85")
    ap.add_argument("--detect-aspect", type=float, default=None, dest="detect_aspect",
                    help="候选宽高比上限，默认 10")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="只检测并出预览图，不处理整片")
    ap.add_argument("--keep", action="store_true", help="保留中间文件")
    ap.add_argument("--log-file", dest="log_file", help="把日志写到文件")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    opts = WMOptions(
        auto=True,
        rect=a.rect,
        mask=a.mask,
        padding=a.padding,
        subvideo=a.subvideo,
        neighbor=a.neighbor,
        ref_stride=a.ref_stride,
        mask_dilation=a.mask_dilation,
        crf=a.crf,
        encoder=a.encoder,
        preset=a.preset,
        detect_thr=a.detect_thr,
        detect_fill=a.detect_fill,
        detect_aspect=a.detect_aspect,
        keep=a.keep,
        dry_run=a.dry_run,
    )
    emit = cli_emitter(a.log_file)
    try:
        run_wm(a.video, opts, emit, out=a.out)
        return 0
    except Cancelled:
        emit.cancelled_event()
        return 3
    except JobError as e:
        emit.error(str(e), e.hint)
        return 1


if __name__ == "__main__":
    sys.exit(main())

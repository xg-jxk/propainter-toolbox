# -*- coding: utf-8 -*-
"""任务参数对象（GUI / JSONL 任务 / CLI 共用）。"""
import os
from dataclasses import asdict, dataclass, field
from typing import Optional


def _get(d, key, default):
    v = d.get(key, default)
    return default if v is None else v


@dataclass
class RepairOptions:
    """区域修复（去除画面中指定区域：字幕、台标、杂物、角标…）。"""

    auto: bool = True
    rect: Optional[str] = None          # "x,y,w,h"
    mask: Optional[str] = None          # 掩码文件或目录
    padding: float = 0.45
    subvideo: int = 40
    neighbor: int = 10
    ref_stride: int = 12
    mask_dilation: int = 2
    crf: int = 17
    encoder: str = "auto"
    preset: Optional[str] = None
    detect_thr: float = 0.62
    detect_fill: Optional[float] = None
    detect_aspect: Optional[float] = None
    keep: bool = False
    dry_run: bool = False

    @classmethod
    def from_dict(cls, d=None):
        d = d or {}
        return cls(
            auto=bool(_get(d, "auto", True)),
            rect=_get(d, "rect", None),
            mask=_get(d, "mask", None),
            padding=float(_get(d, "padding", 0.45)),
            subvideo=int(_get(d, "subvideo", 40)),
            neighbor=int(_get(d, "neighbor", 10)),
            ref_stride=int(_get(d, "ref_stride", 12)),
            mask_dilation=int(_get(d, "mask_dilation", 2)),
            crf=int(_get(d, "crf", 17)),
            encoder=str(_get(d, "encoder", "auto")),
            preset=_get(d, "preset", None),
            detect_thr=float(_get(d, "detect_thr", 0.62)),
            detect_fill=(None if d.get("detect_fill") in (None, "") else float(d["detect_fill"])),
            detect_aspect=(None if d.get("detect_aspect") in (None, "") else float(d["detect_aspect"])),
            keep=bool(_get(d, "keep", False)),
            dry_run=bool(_get(d, "dry_run", False)),
        )

    def validate(self):
        from .events import JobError
        if not (0.0 <= self.padding <= 2.0):
            raise JobError("padding 必须在 0~2 之间")
        if self.subvideo < 5:
            raise JobError("subvideo 至少为 5（建议 20~80）")
        if self.neighbor < 1:
            raise JobError("neighbor 至少为 1（建议 10）")
        if self.ref_stride < 1:
            raise JobError("ref_stride 至少为 1（建议 10~12）")
        if self.mask_dilation < 0:
            raise JobError("mask_dilation 不能为负")
        if not (0 <= self.crf <= 51):
            raise JobError("crf 必须在 0~51 之间（17 常用，越小越清晰）")
        if self.encoder not in ("auto", "x264", "nvenc"):
            raise JobError("encoder 只能是 auto / x264 / nvenc")
        if self.rect:
            parts = self.rect.replace("，", ",").split(",")
            if len(parts) != 4:
                raise JobError("rect 格式应为 x,y,w,h", "例如 1314,918,320,120")
            try:
                w, h = int(parts[2]), int(parts[3])
            except ValueError:
                raise JobError("rect 里的四个值必须是整数")
            if w <= 0 or h <= 0:
                raise JobError("rect 的宽高必须大于 0")


@dataclass
class SROptions:
    scale: int = 2
    denoise: Optional[int] = None       # None = 按分辨率自动
    model: str = "models-pro"
    max_output_long: int = 7680      # 0 = 不限制
    crf: int = 17
    encoder: str = "auto"
    preset: Optional[str] = None
    keep: bool = False

    @classmethod
    def from_dict(cls, d=None):
        d = d or {}
        den = d.get("denoise", None)
        return cls(
            scale=int(_get(d, "scale", 2)),
            denoise=(None if den in (None, "") else int(den)),
            model=str(_get(d, "model", "models-pro")),
            max_output_long=int(_get(d, "max_output_long", 7680)),
            crf=int(_get(d, "crf", 17)),
            encoder=str(_get(d, "encoder", "auto")),
            preset=_get(d, "preset", None),
            keep=bool(_get(d, "keep", False)),
        )

    def validate(self):
        from .events import JobError
        if self.scale not in (2, 3, 4):
            raise JobError("scale 只能是 2 / 3 / 4")
        if self.denoise not in (None, -1, 0, 1, 2, 3):
            raise JobError("denoise 只能是 -1 / 0 / 1 / 2 / 3")
        if not (0 <= self.crf <= 51):
            raise JobError("crf 必须在 0~51 之间")
        if self.max_output_long and not (2048 <= self.max_output_long <= 16384):
            raise JobError("max_output_long 只能是 0（不限制）或 2048~16384")
        if self.encoder not in ("auto", "x264", "nvenc"):
            raise JobError("encoder 只能是 auto / x264 / nvenc")


@dataclass
class JobSpec:
    mode: str = "repair"                # repair | sr | pipeline
    video: str = ""
    out: Optional[str] = None
    workdir: Optional[str] = None
    log_file: Optional[str] = None
    intermediate_crf: int = 12
    clip_seconds: float = 0.0           # >0 表示测试模式：只处理这一段
    clip_start: float = 0.0
    repair: RepairOptions = field(default_factory=RepairOptions)
    sr: SROptions = field(default_factory=SROptions)

    def to_dict(self):
        return {
            "mode": self.mode,
            "video": self.video,
            "out": self.out,
            "workdir": self.workdir,
            "log_file": self.log_file,
            "intermediate_crf": self.intermediate_crf,
            "clip_seconds": self.clip_seconds,
            "clip_start": self.clip_start,
            "repair": asdict(self.repair),
            "sr": asdict(self.sr),
        }


def _unique(base, ext=".mp4"):
    cand = base + ext
    i = 2
    while os.path.exists(cand):
        cand = "%s(%d)%s" % (base, i, ext)
        i += 1
    return cand


def default_out(video, mode="repair", scale=2, preview=False):
    """按模式给出默认输出路径；重名自动加 (2)(3)…

    preview=True 时只加 `_预览` 后缀（测试模式），不区分修复/超分。
    """
    video = os.path.abspath(video)
    directory = os.path.dirname(video)
    name = os.path.splitext(os.path.basename(video))[0]
    if preview:
        suffix = "_预览"
    elif mode == "repair":
        suffix = "_已修复"
    elif mode == "sr":
        suffix = "_%dx" % int(scale)
    else:
        suffix = "_已修复_%dx" % int(scale)
    return _unique(os.path.join(directory, name + suffix))

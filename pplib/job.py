# -*- coding: utf-8 -*-
"""任务编排：校验 spec、串联去水印+超分、批量输入归一化。"""
import os
import shutil
import tempfile
import time
from dataclasses import replace

from .const import MAX_QUEUE, VIDEO_EXTS, normalize_inputs  # noqa: F401  (对外兼容)
from .events import JobError, ScaledEmitter
from .options import JobSpec, SROptions, WMOptions, default_out
from .sr import run_sr
from .wm import run_wm


def parse_spec(d):
    """把 JSON 字典校验成 JobSpec；失败抛 JobError（消息直接给用户看）。"""
    if not isinstance(d, dict):
        raise JobError("任务描述必须是 JSON 对象")
    mode = str(d.get("mode") or "wm").strip().lower()
    if mode not in ("wm", "sr", "pipeline"):
        raise JobError("mode 只能是 wm / sr / pipeline")

    video = str(d.get("video") or "").strip()
    if not video:
        raise JobError("缺少 video 字段")
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        raise JobError("找不到视频：%s" % video, "文件可能被移动/删除，或路径含非法字符")

    def _opt_str(key):
        v = d.get(key)
        return str(v) if v else None

    try:
        icrf = int(d.get("intermediate_crf", 12))
    except (TypeError, ValueError):
        raise JobError("intermediate_crf 必须是整数")

    spec = JobSpec(
        mode=mode,
        video=video,
        out=_opt_str("out"),
        workdir=_opt_str("workdir"),
        log_file=_opt_str("log_file"),
        intermediate_crf=icrf,
        wm=WMOptions.from_dict(d.get("wm")),
        sr=SROptions.from_dict(d.get("sr")),
    )
    if not (0 <= spec.intermediate_crf <= 51):
        raise JobError("intermediate_crf 必须在 0~51 之间（12 常用，0 为无损但文件巨大）")
    spec.wm.validate()
    spec.sr.validate()
    return spec


def run_job(spec, emit):
    """执行一个任务；返回结果字典。"""
    if spec.mode == "wm":
        return run_wm(spec.video, spec.wm, emit, out=spec.out)
    if spec.mode == "sr":
        return run_sr(spec.video, spec.sr, emit, out=spec.out)
    return _run_pipeline(spec, emit)


def _run_pipeline(spec, emit):
    t0 = time.time()
    jobdir = tempfile.mkdtemp(prefix="ppline_")
    clean = os.path.join(jobdir, "clean.mp4")
    keep = bool(spec.wm.keep or spec.sr.keep)
    try:
        emit.log("步骤 1/2  去水印 ...")
        wm_opts = replace(spec.wm, crf=spec.intermediate_crf)
        run_wm(spec.video, wm_opts, ScaledEmitter(emit, 0.0, 46.0), out=clean, final=False)
        emit.check_cancel()

        emit.log("步骤 2/2  超分 ...")
        out = spec.out or default_out(spec.video, "pipeline", spec.sr.scale)
        res = run_sr(clean, spec.sr, ScaledEmitter(emit, 46.0, 98.0), out=out, final=False)
        emit.total_pct(100)
        size = os.path.getsize(out) if os.path.isfile(out) else None
        emit.done(out=out, size=size, elapsed=time.time() - t0,
                  extra={"frames": res.get("frames"), "mode": "pipeline"})
        return {"out": out, "size": size, "elapsed": time.time() - t0,
                "frames": res.get("frames")}
    finally:
        if keep:
            emit.log("中间文件：%s" % jobdir)
        else:
            shutil.rmtree(jobdir, ignore_errors=True)

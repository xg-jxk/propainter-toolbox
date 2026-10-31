# -*- coding: utf-8 -*-
"""任务编排：校验 spec、串联区域修复 + 超分。"""
import os
import shutil
import tempfile
import time
from dataclasses import replace

from .const import temp_root, MAX_QUEUE, VIDEO_EXTS, normalize_inputs  # noqa: F401  (对外兼容)
from .events import JobError, ScaledEmitter
from .ffmpeg import probe_size, scale_video
from .options import JobSpec, RepairOptions, SROptions, default_out
from .repair import run_repair
from .scaling import plan_scale, target_tag
from .sr import run_sr


def parse_spec(d):
    """把 JSON 字典校验成 JobSpec；失败抛 JobError（消息直接给用户看）。"""
    if not isinstance(d, dict):
        raise JobError("任务描述必须是 JSON 对象")
    mode = str(d.get("mode") or "repair").strip().lower()
    if mode not in ("repair", "sr", "pipeline"):
        raise JobError("mode 只能是 repair / sr / pipeline")

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

    def _opt_float(key):
        v = d.get(key)
        if v in (None, ""):
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            raise JobError("%s 必须是数字" % key)

    clip_seconds = _opt_float("clip_seconds")
    clip_start = _opt_float("clip_start")
    if clip_seconds < 0 or clip_seconds > 600:
        raise JobError("测试模式时长必须在 0~600 秒之间")
    if clip_start < 0:
        raise JobError("起始时间不能是负数")

    spec = JobSpec(
        mode=mode,
        video=video,
        out=_opt_str("out"),
        clip_seconds=clip_seconds,
        clip_start=clip_start,
        workdir=_opt_str("workdir"),
        log_file=_opt_str("log_file"),
        intermediate_crf=icrf,
        repair=RepairOptions.from_dict(d.get("repair")),
        sr=SROptions.from_dict(d.get("sr")),
    )
    if not (0 <= spec.intermediate_crf <= 51):
        raise JobError("intermediate_crf 必须在 0~51 之间（12 常用，0 为无损但文件巨大）")
    spec.repair.validate()
    spec.sr.validate()
    return spec


def run_job(spec, emit):
    """执行一个任务；返回结果字典。clip_seconds > 0 时只处理这一小段（测试模式）。"""
    if spec.clip_seconds and spec.clip_seconds > 0:
        return _run_preview(spec, emit)
    return _run_once(spec, emit)


def _run_once(spec, emit, final=True):
    if spec.mode == "repair":
        return run_repair(spec.video, spec.repair, emit, out=spec.out, final=final)
    if spec.mode == "sr":
        return run_sr(spec.video, spec.sr, emit, out=spec.out, final=final)
    return _run_pipeline(spec, emit, final=final)


def _run_preview(spec, emit):
    """切出 [clip_start, clip_start+clip_seconds) 再走正常流程，输出 *_预览.mp4。"""
    from .ffmpeg import cut_clip, probe

    seconds = float(spec.clip_seconds)
    start = max(0.0, float(spec.clip_start or 0))
    dur = probe(spec.video)[2]
    if dur and start >= dur - 0.05:
        raise JobError("起始时间 %.1fs 超出视频时长 %.1fs" % (start, dur),
                       "把「从第 N 秒开始」改小一些")
    if dur and start + seconds > dur:
        seconds = max(0.5, dur - start)
        emit.log("视频只有 %.1fs，预览段缩到 %.1fs" % (dur, seconds))

    emit.log("测试模式：只处理 %.1fs ~ %.1fs（共 %.1fs），输出到源目录、加 _预览 后缀"
             % (start, start + seconds, seconds))
    out = spec.out or default_out(spec.video, spec.mode, spec.sr.scale, preview=True,
                                  tag=target_tag(spec.sr.target_long))
    tmpdir = tempfile.mkdtemp(prefix="ppclip_", dir=temp_root())
    clip = os.path.join(tmpdir, "clip.mp4")
    try:
        cut_clip(spec.video, clip, start, seconds, emit=emit)
        sub = replace(spec, video=clip, out=out, clip_seconds=0.0, clip_start=0.0)
        res = _run_once(sub, emit, final=False) or {}
        elapsed = float(res.get("elapsed") or 0)
        made = res.get("out") or (out if os.path.isfile(out) else "")
        # 修复被跳过但超分照样出片的情况也要报成品（以前会误报成"跳过"）
        if not made:
            reason = res.get("reason")
            emit.done(out=None, size=None, elapsed=elapsed,
                      extra={"frames": res.get("frames"), "skipped": "repair",
                             "reason": reason, "preview": True})
            return dict(res, preview=True, clip_start=start, clip_seconds=seconds)
        size = os.path.getsize(made) if os.path.isfile(made) else None
        emit.done(out=made, size=size, elapsed=elapsed,
                  extra={"frames": res.get("frames"), "preview": True,
                         "clip_start": start, "clip_seconds": seconds})
        return {"out": made, "size": size, "elapsed": elapsed,
                "frames": res.get("frames"), "preview": True}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_pipeline(spec, emit, final=True):
    t0 = time.time()
    jobdir = tempfile.mkdtemp(prefix="ppline_", dir=temp_root())
    clean = os.path.join(jobdir, "clean.mp4")
    keep = bool(spec.repair.keep or spec.sr.keep)
    target = int(getattr(spec.sr, "target_long", 0) or 0)
    cap = int(getattr(spec.sr, "max_output_long", 0) or 0)
    tag = target_tag(target) if target else ""
    plan = None
    if target:
        w, h = probe_size(spec.video)
        plan = plan_scale(w, h, target, cap)
        if plan.get("reason"):
            emit.log(plan["reason"])
    # 源已经达标：这轮不跑超分模型，修复的成品直接按目标尺寸编码（只编码一次）
    direct = plan["final"] if (plan and not plan["need_sr"]) else None
    try:
        emit.log("步骤 1/2  区域修复 ...")
        repair_opts = replace(spec.repair, crf=spec.intermediate_crf)
        # 中间文件不封顶：它还要喂给超分，这里省几 MB 会放大成画质损失
        rep = run_repair(spec.video, repair_opts, ScaledEmitter(emit, 0.0, 46.0),
                         out=clean, final=False, limit=False, out_size=direct)
        skipped = bool((rep or {}).get("skipped"))
        reason = (rep or {}).get("reason")
        if skipped:
            emit.log("⚠ 区域修复已跳过（%s）" % reason)
        emit.check_cancel()

        if direct is not None:
            out = spec.out or default_out(spec.video, "pipeline", spec.sr.scale, tag=tag)
            emit.log("步骤 2/2  跳过超分，统一输出 %dx%d" % (direct[0], direct[1]))
            use_cap = bool(getattr(spec.sr, "cap_size", True))
            try:
                if skipped or not os.path.isfile(clean):
                    scale_video(spec.video, out, direct, crf=spec.sr.crf,
                                encoder=spec.sr.encoder, preset=spec.sr.preset,
                                emit=emit, limit=use_cap)
                else:
                    shutil.copyfile(clean, out)      # clean 已经是目标尺寸
            except OSError as e:
                raise JobError("统一尺寸成品无法落盘：%s" % e)
            size = os.path.getsize(out) if os.path.isfile(out) else None
            emit.total_pct(100)
            extra = {"frames": rep.get("frames"), "mode": "pipeline",
                     "skipped": "sr", "reason": plan.get("reason") or ""}
            if final:
                emit.done(out=out, size=size, elapsed=time.time() - t0, extra=extra)
            return {"out": out, "size": size, "elapsed": time.time() - t0,
                    "frames": rep.get("frames"), "skipped": True,
                    "reason": plan.get("reason") or ""}

        emit.log("步骤 2/2  超分 ...")
        # 跳过修复时 super-res 直接吃原视频（clean.mp4 根本不存在）
        src = spec.video if skipped else clean
        if spec.out:
            out = spec.out
        elif skipped:
            out = default_out(spec.video, "sr", spec.sr.scale, tag=tag)   # 没有修复，名字不带「_已修复」
        else:
            out = default_out(spec.video, "pipeline", spec.sr.scale, tag=tag)
        res = run_sr(src, spec.sr, ScaledEmitter(emit, 46.0, 98.0), out=out, final=False)
        if (res or {}).get("skipped"):
            # 超分被跳过：交付修复版（没做修复的话就没产出）
            reason = (res or {}).get("reason") or "超分被跳过"
            if skipped:
                emit.log("⚠ 超分已跳过：%s" % reason)
                emit.done(out=None, size=None, elapsed=time.time() - t0,
                          extra={"frames": rep.get("frames"), "skipped": "both",
                                 "reason": reason})
                return {"skipped": True, "reason": reason, "out": None}
            final_out = spec.out or default_out(spec.video, "repair")
            try:
                shutil.copyfile(clean, final_out)
            except OSError as e:
                raise JobError("超分跳过，但修复版无法落盘：%s" % e)
            size = os.path.getsize(final_out) if os.path.isfile(final_out) else None
            emit.log("⚠ 超分已跳过：%s；已交付修复版 %s" % (reason, final_out))
            emit.total_pct(100)
            emit.done(out=final_out, size=size, elapsed=time.time() - t0,
                      extra={"frames": rep.get("frames"), "mode": "pipeline",
                             "skipped": "sr", "reason": reason})
            return {"out": final_out, "size": size, "elapsed": time.time() - t0,
                    "skipped": True, "reason": reason}
        emit.total_pct(100)
        size = os.path.getsize(out) if os.path.isfile(out) else None
        extra = {"frames": res.get("frames"), "mode": "pipeline"}
        if skipped:
            extra.update({"skipped": "repair", "reason": reason})
        if final:
            emit.done(out=out, size=size, elapsed=time.time() - t0, extra=extra)
        result = {"out": out, "size": size, "elapsed": time.time() - t0,
                  "frames": res.get("frames")}
        if skipped:
            result.update({"skipped": "repair", "reason": reason})
        return result
    finally:
        if keep:
            emit.log("中间文件：%s" % jobdir)
        else:
            shutil.rmtree(jobdir, ignore_errors=True)

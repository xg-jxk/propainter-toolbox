# -*- coding: utf-8 -*-
"""JSONL 任务进程：GUI（或其它前端）用它跑单个任务。

用法：
    python -m pplib.runner --spec job.json --jsonl

stdout 每行一个 JSON 事件（见 pplib.events）；退出码：
    0 成功 / 1 失败 / 3 已取消
"""
import argparse
import json
import os
import sys

from . import logfmt
from .events import (Cancelled, Emitter, JobError, file_sink, human_sink,
                     jsonl_sink, tee_sink)
from .job import parse_spec, run_job


def _print_banner(spec, args):
    """命令行单任务的开头两行：分隔 + 源/目标信息。"""
    name = os.path.basename(spec.video)
    print(logfmt.bar("开始：%s" % name))
    try:
        from .ffmpeg import probe_size
        from .scaling import plan_scale
        w, h = probe_size(spec.video)
        target = int(getattr(spec.sr, "target_long", 0) or 0)
        if w and h and target:
            plan = plan_scale(w, h, target,
                              int(getattr(spec.sr, "max_output_long", 0) or 0))
            print(logfmt.meta_line(w, h, *plan["final"],
                                   preview=bool(getattr(spec, "clip_seconds", 0))))
        elif w and h:
            print(logfmt.meta_line(w, h))
    except Exception:
        pass


def main(argv=None):
    try:  # Windows 控制台默认 GBK，中文 JSON 必须按 UTF-8 输出给 GUI
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="pplib.runner")
    ap.add_argument("--spec", required=True, help="任务 JSON 文件路径")
    ap.add_argument("--jsonl", action="store_true", help="输出 JSON 事件流而不是人读日志")
    ap.add_argument("--clip", type=float, default=None,
                    help="测试模式：只处理这么多秒（覆盖 spec）")
    ap.add_argument("--clip-start", type=float, default=None, help="测试模式起始秒数")
    args = ap.parse_args(argv)

    sink = jsonl_sink() if args.jsonl else None
    emit = Emitter(sink)
    log_sink = None
    try:
        with open(args.spec, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        log_path = (data or {}).get("log_file") if isinstance(data, dict) else None
        if log_path:
            log_sink = file_sink(log_path)
            emit = Emitter(tee_sink(sink or human_sink, log_sink))

        spec = parse_spec(data)
        if args.clip is not None or args.clip_start is not None:
            from dataclasses import replace as _replace
            spec = _replace(
                spec,
                clip_seconds=float(args.clip if args.clip is not None else spec.clip_seconds),
                clip_start=float(args.clip_start if args.clip_start is not None else spec.clip_start))
        if not args.jsonl:            # CLI 才加分隔（GUI 自己画带颜色的）
            _print_banner(spec, args)
        result = run_job(spec, emit)
        if not args.jsonl:
            print(logfmt.bar())
            print("结果：%s" % (result or {}))
        return 0
    except Cancelled:
        emit.cancelled_event()
        return 3
    except JobError as e:
        emit.error(str(e), getattr(e, "hint", None))
        return 1
    except KeyboardInterrupt:
        emit.cancelled_event()
        return 3
    except Exception as e:  # 兜底，避免 GUI 只看到进程退出码
        import traceback
        tb = traceback.format_exc()
        emit.log("未预期异常，完整堆栈如下：")
        for line in tb.rstrip().splitlines()[-25:]:
            emit.log("  " + line)
        hint = "把上面这段堆栈发出来即可定位；显存不足可把 subvideo / padding 调小"
        emit.error("%s: %s" % (type(e).__name__, e), hint)
        return 1
    finally:
        if log_sink is not None:
            try:
                log_sink.handle.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())

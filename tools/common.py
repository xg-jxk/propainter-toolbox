# -*- coding: utf-8 -*-
"""共享工具：路径 / 日志 / ffmpeg / 子进程 / 编码参数。

tools 下的脚本都从这里取，避免每个脚本各写一份 probe()/run()/log()
（旧版有三份实现，措辞和行为会漂移）。
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
CUGAN_DIR = TOOLS / "realcugan"
CUGAN_EXE = CUGAN_DIR / "realcugan-ncnn-vulkan.exe"
WEIGHTS = ROOT / "weights"

_ffmpeg = None
_log_fh = None
_encoder = None

_FPS_TBR = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*tbr")
_FPS_RAW = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*fps")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


# --------------------------------------------------------------- 日志

def set_log_file(path):
    """把 log()/run() 的输出同时追加到文件，便于事后排查。"""
    global _log_fh
    if _log_fh:
        try:
            _log_fh.close()
        except Exception:
            pass
        _log_fh = None
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    _log_fh = open(path, "a", encoding="utf-8", errors="ignore")


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if _log_fh:
        try:
            _log_fh.write(line + "\n")
            _log_fh.flush()
        except Exception:
            pass


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def dir_size(path):
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


# --------------------------------------------------------------- ffmpeg

def find_ffmpeg():
    """依次尝试：环境变量 FFMPEG → PATH → tools/ffmpeg → imageio-ffmpeg。"""
    global _ffmpeg
    if _ffmpeg:
        return _ffmpeg
    env = os.environ.get("FFMPEG")
    if env and Path(env).is_file():
        _ffmpeg = str(env)
    else:
        p = shutil.which("ffmpeg")
        if p:
            _ffmpeg = p
        else:
            cand = TOOLS / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if cand.is_file():
                _ffmpeg = str(cand)
            else:
                try:
                    import imageio_ffmpeg
                    _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    pass
    if not _ffmpeg:
        raise SystemExit("找不到 ffmpeg：请安装并加入 PATH，"
                         "或把 ffmpeg.exe 放到 tools/ffmpeg/ 下（setup.ps1 会通过 imageio-ffmpeg 自动准备）")
    return _ffmpeg


def probe(video):
    """返回 (fps, 是否有音轨, 时长秒)。fps 优先取精确的 tbr，取不到退回 30。"""
    ff = find_ffmpeg()
    p = subprocess.run([ff, "-hide_banner", "-i", str(video)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, errors="ignore")
    info = p.stderr or ""

    fps = 0.0
    m = _FPS_TBR.search(info) or _FPS_RAW.search(info)
    if m:
        try:
            fps = float(m.group(1))
        except ValueError:
            fps = 0.0
    # 老片子/异常封装可能给出 1000 之类的假 tbr，做个合理区间兜底
    if not (5.0 <= fps <= 240.0):
        fps = 30.0

    d = _DURATION.search(info)
    if d:
        dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    else:
        dur = None

    return fps, ("Audio:" in info), dur


# --------------------------------------------------------------- 子进程

def run(cmd, cwd=None, env=None, quiet=True, log_path=None, timeout=None):
    """跑子进程；失败时抛出带退出码的 SystemExit，并把输出写进日志文件。"""
    kw = {"cwd": cwd, "env": env, "timeout": timeout}
    if quiet:
        kw.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  text=True, errors="ignore")
    p = subprocess.run(cmd, **kw)

    if quiet:
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        dest = log_path or (_log_fh.name if _log_fh else None)
        if dest:
            try:
                with open(dest, "a", encoding="utf-8", errors="ignore") as fh:
                    fh.write("\n$ %s\n%s\n" % (" ".join(str(c) for c in cmd), out))
            except Exception:
                pass

    if p.returncode != 0:
        if quiet:
            tail = ((p.stdout or "") + "\n" + (p.stderr or ""))[-4000:]
            if tail.strip():
                sys.stderr.write(tail + "\n")
        raise SystemExit("命令失败（退出码 %d）：%s" % (p.returncode, os.path.basename(str(cmd[0]))))
    return p


def ensure_out_writable(path):
    """在真正开跑之前确认输出目录存在且可写，避免跑了一小时才失败。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise SystemExit("无法创建输出目录 %s：%s" % (directory, e))
    probe_file = os.path.join(directory, ".pp_write_test")
    try:
        with open(probe_file, "wb") as fh:
            fh.write(b"0")
        os.remove(probe_file)
    except OSError as e:
        raise SystemExit("输出目录不可写 %s：%s" % (directory, e))


# --------------------------------------------------------------- 编码参数

def pick_encoder(prefer="auto"):
    """auto → 有 h264_nvenc 就用硬件编码，否则 libx264。也可用 PP_ENCODER 环境变量覆盖。"""
    global _encoder
    prefer = (prefer or "auto").lower()
    if prefer in ("libx264", "cpu"):
        prefer = "x264"
    if prefer in ("h264_nvenc", "gpu"):
        prefer = "nvenc"
    if prefer not in ("auto", "x264", "nvenc"):
        raise SystemExit("--encoder 只能是 auto / x264 / nvenc")
    env = (os.environ.get("PP_ENCODER") or "").lower()
    if prefer == "auto" and env in ("x264", "nvenc"):
        prefer = env

    if prefer == "x264":
        return "libx264"
    if prefer == "nvenc":
        return "h264_nvenc"
    if _encoder:
        return _encoder

    _encoder = "libx264"
    try:
        p = subprocess.run([find_ffmpeg(), "-hide_banner", "-encoders"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, errors="ignore")
        if "h264_nvenc" in (p.stdout or ""):
            _encoder = "h264_nvenc"
    except Exception:
        pass
    return _encoder


def video_encode_args(encoder, crf, preset=None):
    """返回视频编码参数（不含输出文件）。"""
    enc = (encoder or "libx264").lower()
    if enc == "h264_nvenc":
        # vbr + cq 才能和 x264 的 crf 大致对标；b:v 0 交给 cq 控制码率
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", str(int(crf)), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", preset or "medium", "-crf", str(int(crf))]


def encode_frames(frames_dir, src_video, out, fps, n_frames, has_audio,
                  encoder="auto", crf=17, preset=None):
    """把 frames_dir 下 00000.png 起的序列加上 src_video 的音轨，编码成 out。

    音频优先直接 copy；某些 mp4 不支持的编码（PCM / Opus）会失败，
    此时自动退回 AAC 重编一次 —— 避免跑到最后一小时才炸。
    """
    pattern = os.path.join(frames_dir, "%05d.png")
    duration = "%.3f" % (float(n_frames) / float(fps))
    head = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "%g" % fps, "-i", pattern, "-i", str(src_video), "-map", "0:v:0"]
    if has_audio:
        head += ["-map", "1:a:0"]
    head += video_encode_args(pick_encoder(encoder), crf, preset)
    head += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]

    if not has_audio:
        run(head + [out])
        return
    try:
        run(head + ["-c:a", "copy", "-t", duration, out])
    except SystemExit:
        log("音频流无法直接拷贝，改用 AAC 重新编码 ...")
        run(head + ["-c:a", "aac", "-b:a", "192k", "-t", duration, out])

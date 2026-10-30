# -*- coding: utf-8 -*-
"""ffmpeg 探测、抽帧、编码、子进程执行。"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .events import JobError

def _resolve_root():
    """项目根目录：源码运行取 pplib 的上一级；打包后优先 PP_ROOT / 安装目录。"""
    env = os.environ.get("PP_ROOT")
    if env and os.path.isdir(env):
        return Path(env)
    if getattr(sys, "frozen", False):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            cand = Path(local) / "ProPainterToolbox" / "runtime"
            if (cand / "pplib").is_dir():
                return cand
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT = _resolve_root()
TOOLS = ROOT / "tools"
CUGAN_DIR = TOOLS / "realcugan"
CUGAN_EXE = CUGAN_DIR / "realcugan-ncnn-vulkan.exe"
WEIGHTS = ROOT / "weights"
INFERENCE = ROOT / "inference_propainter.py"

_ffmpeg = None
_encoder = None

_FPS_TBR = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*tbr")
_FPS_RAW = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*fps")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


# --------------------------------------------------------------- ffmpeg

def find_ffmpeg():
    """依次尝试：环境变量 FFMPEG → PATH → tools/ffmpeg → imageio-ffmpeg。"""
    global _ffmpeg
    if _ffmpeg:
        return _ffmpeg
    env = os.environ.get("FFMPEG")
    if env and Path(env).is_file():
        _ffmpeg = str(env)
        return _ffmpeg
    p = shutil.which("ffmpeg")
    if p:
        _ffmpeg = p
        return _ffmpeg
    cand = TOOLS / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if cand.is_file():
        _ffmpeg = str(cand)
        return _ffmpeg
    try:
        import imageio_ffmpeg
        _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    if not _ffmpeg:
        raise JobError("找不到 ffmpeg",
                       "请先运行 setup.cmd 安装依赖（imageio-ffmpeg 会自带一份），"
                       "或把 ffmpeg.exe 放进 tools/ffmpeg/")
    return _ffmpeg


def cut_clip(src, dst, start, seconds, emit=None):
    """切出 [start, start+seconds) 的一段；重编码保证时间轴精确、开头无负时间戳。"""
    ff = find_ffmpeg()
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
    if start and float(start) > 0.001:
        cmd += ["-ss", "%.3f" % float(start)]
    cmd += ["-i", str(src), "-t", "%.3f" % float(seconds),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-c:a", "aac", "-b:a", "192k",
            "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
            str(dst)]
    run(cmd, emit=emit, label="裁剪预览片段")
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise JobError("预览片段生成失败：%s" % dst, "检查磁盘空间与源文件是否可读")
    return dst


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
    if not (5.0 <= fps <= 240.0):
        fps = 30.0

    d = _DURATION.search(info)
    dur = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else None
    return fps, ("Audio:" in info), dur




_SIZE_RE = re.compile(r"Video:.*?[,\s](\d{2,5})x(\d{2,5})")


def probe_size(video):
    """只取分辨率，返回 (宽, 高)；失败返回 (0, 0)。"""
    try:
        p = subprocess.run([find_ffmpeg(), "-hide_banner", "-i", str(video)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, errors="ignore")
        m = _SIZE_RE.search(p.stderr or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


# --------------------------------------------------------------- 子进程

def _stderr_tail(path, limit=3000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
        return data[-limit:]
    except Exception:
        return ""


def run(cmd, cwd=None, env=None, emit=None, label=None):
    """跑一个短命令；失败时抛 JobError（带 stderr 尾巴）。"""
    tmp = tempfile.NamedTemporaryFile(prefix="ppcmd_", suffix=".log", delete=False)
    tmp.close()
    try:
        with open(tmp.name, "wb") as err:
            p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=err)
        if p.returncode != 0:
            tail = _stderr_tail(tmp.name)
            if emit:
                emit.log(tail.strip()[-1500:])
            raise JobError("%s失败（退出码 %d）"
                           % (label or os.path.basename(str(cmd[0])), p.returncode),
                           "详细输出见日志；常见原因是磁盘满、路径含非法字符或文件被占用")
        return p
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


def run_stream(cmd, on_line=None, cwd=None, env=None, emit=None, label=None):
    """逐行读取子进程 stdout（用于解析进度），stderr 落到临时文件。

    取消时抛 Cancelled，并在 finally 里 kill 子进程（含其子进程树）。
    """
    tmp = tempfile.NamedTemporaryFile(prefix="ppcmd_", suffix=".log", delete=False)
    tmp.close()
    p = None
    try:
        with open(tmp.name, "wb") as err:
            p = subprocess.Popen(cmd, cwd=cwd, env=env,
                                 stdout=subprocess.PIPE, stderr=err,
                                 encoding="utf-8", errors="replace", bufsize=1)
            try:
                for line in p.stdout:
                    if on_line is not None:
                        on_line(line.rstrip("\r\n"))
            finally:
                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass
            rc = p.wait()
        if rc != 0:
            tail = _stderr_tail(tmp.name)
            if emit:
                emit.log(tail.strip()[-1500:])
            raise JobError("%s失败（退出码 %d）" % (label or os.path.basename(str(cmd[0])), rc),
                           "常见原因：显存不足（把 --subvideo 降到 20）、磁盘满、视频损坏")
    finally:
        if p is not None and p.poll() is None:
            try:
                p.kill()
                p.wait()
            except Exception:
                pass
        try:
            os.remove(tmp.name)
        except OSError:
            pass


# --------------------------------------------------------------- 文件/空间

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


def ensure_out_writable(path):
    """提前验证输出可写，避免跑完一小时才在编码那步失败。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise JobError("无法创建输出目录 %s：%s" % (directory, e))
    probe_file = os.path.join(directory, ".pp_write_test")
    try:
        with open(probe_file, "wb") as fh:
            fh.write(b"0")
        os.remove(probe_file)
    except OSError as e:
        raise JobError("输出目录不可写 %s：%s" % (directory, e),
                       "换一个输出目录，或检查只读/同步盘（OneDrive 占位文件）")


# --------------------------------------------------------------- 抽帧

def extract_frames(video, out_dir, fps, duration, emit=None, pct_from=0.0, pct_to=10.0,
                   cwd=None):
    """按恒定帧率抽帧到 out_dir/00000.png，并按 ffmpeg 的 frame= 上报进度。"""
    ff = find_ffmpeg()
    os.makedirs(out_dir, exist_ok=True)
    total = None
    if duration and duration > 0 and fps > 0:
        total = max(1, int(round(duration * fps)))

    def on_line(line):
        if emit is None:
            return
        if line.startswith("frame="):
            try:
                n = int(line.split("=", 1)[1])
            except (IndexError, ValueError):
                return
            if total:
                pct = pct_from + (pct_to - pct_from) * min(1.0, float(n) / total)
                emit.total_pct(pct, "抽帧")
                emit.progress(n, total, "抽帧")
            else:
                emit.total_pct(pct_from, "抽帧")

    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1", "-i", str(video),
           "-vf", "fps=%g" % fps, "-start_number", "0", "-y",
           os.path.join(out_dir, "%05d.png")]
    run_stream(cmd, on_line, cwd=cwd, emit=emit, label="抽帧")

    names = sorted(os.listdir(out_dir))
    if not names:
        raise JobError("抽帧结果为空", "磁盘是否已满？或视频编码不受支持（可先用播放器另存为 H.264）")
    return names


# --------------------------------------------------------------- 编码

def pick_encoder(prefer="auto"):
    """auto → 有 h264_nvenc 就用硬件编码，否则 libx264；PP_ENCODER 可覆盖。"""
    global _encoder
    prefer = (prefer or "auto").lower()
    if prefer in ("libx264", "cpu"):
        prefer = "x264"
    if prefer in ("h264_nvenc", "gpu"):
        prefer = "nvenc"
    if prefer not in ("auto", "x264", "nvenc"):
        raise JobError("--encoder 只能是 auto / x264 / nvenc")
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
    enc = (encoder or "libx264").lower()
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", str(int(crf)), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", preset or "medium", "-crf", str(int(crf))]



#: H.264 NVENC 的硬限制（宽/高都不能超过它）；HEVC 能到 8192
NVENC_MAX_SIDE = 4096


def _png_size(path):
    """读 PNG 头拿宽高，避免为了一个尺寸去 import cv2。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        import struct
        w, h = struct.unpack(">II", head[16:24])
        return int(w), int(h)
    except OSError:
        return 0, 0


def _first_frame_size(frames_dir):
    try:
        names = sorted(n for n in os.listdir(frames_dir) if n.lower().endswith(".png"))
    except OSError:
        return 0, 0
    return _png_size(os.path.join(frames_dir, names[0])) if names else (0, 0)


def encode_frames(frames_dir, src_video, out, fps, n_frames, has_audio,
                  encoder="auto", crf=17, preset=None, emit=None):
    """把 frames_dir 下 00000.png 起的序列加上音轨，编码成 out。

    音频优先 copy；mp4 不支持的编码（PCM/Opus）失败后自动退回 AAC 重编一次。
    """
    ff = find_ffmpeg()
    pattern = os.path.join(frames_dir, "%05d.png")
    duration = "%.3f" % (float(n_frames) / float(fps))

    width, height = _first_frame_size(frames_dir)
    enc = pick_encoder(encoder)
    # H.264 NVENC 最大 4096；4x 放大到 5120x2880 这类尺寸只能走 CPU
    if enc == "h264_nvenc" and (width > NVENC_MAX_SIDE or height > NVENC_MAX_SIDE):
        if emit:
            emit.log("[提示] 输出 %dx%d 超过 H.264 NVENC 上限 %d，自动改用 CPU x264 编码"
                     % (width, height, NVENC_MAX_SIDE))
            emit.log("       想继续用显卡编码，把倍率降一档（4x→2x/3x）")
        enc = "libx264"
        preset = preset or "veryfast"
    if emit and width and height:
        emit.log("编码 %dx%d · %s · crf %d" % (width, height, enc, int(crf)))

    head = [ff, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "%g" % fps, "-i", pattern, "-i", str(src_video), "-map", "0:v:0"]
    if has_audio:
        head += ["-map", "1:a:0"]
    head += video_encode_args(enc, crf, preset)
    head += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]

    hint = ("若日志里出现 No capable devices found：输出分辨率超过 H.264 NVENC 上限"
            "（宽高需 ≤%d），把编码器改成 CPU x264 或降低超分倍率" % NVENC_MAX_SIDE)

    def _encode(args):
        try:
            run(args, emit=emit, label="编码")
        except JobError as e:
            raise JobError(str(e), hint)

    if not has_audio:
        _encode(head + [out])
        return
    try:
        _encode(head + ["-c:a", "copy", "-t", duration, out])
    except JobError:
        if emit:
            emit.log("音轨无法直接拷贝，改用 AAC 重新编码 ...")
        _encode(head + ["-c:a", "aac", "-b:a", "192k", "-t", duration, out])


def now():
    return time.time()

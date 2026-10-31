# -*- coding: utf-8 -*-
"""ffmpeg 探测、抽帧、编码、子进程执行。"""
import glob
import os
import re
import shutil
import subprocess

from . import winproc
import sys
import tempfile

from .const import temp_root
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

#: site-packages 里 imageio-ffmpeg 二进制的相对路径（Windows / POSIX 两种布局）
_SITE_FFMPEG_PATTERNS = [
    os.path.join("Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*.exe"),
    os.path.join("lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"),
]


def _venv_ffmpeg():
    """直接按路径找 imageio-ffmpeg 自带的二进制，不依赖 import。

    打包后的 exe 把 imageio_ffmpeg 排除了（83 MB 二进制不值得打进壳），
    在那种进程里 `import imageio_ffmpeg` 会失败 —— 但 venv 里那份 ffmpeg 还在，
    按路径就能拿到。GUI 进程探测分辨率走的就是这条路。

    依次找：项目根的 `.venv` → 当前解释器的 sys.prefix → sys.base_prefix。
    后两个覆盖「测试跑在别的虚拟环境里」「便携版把运行时装在别处」这类情况，
    否则在 CI / 全新克隆里会误报"找不到 ffmpeg"。
    """
    bases = [os.path.join(str(ROOT), ".venv"), sys.prefix, getattr(sys, "base_prefix", sys.prefix)]
    seen = set()
    for base in bases:
        try:
            key = os.path.normcase(os.path.abspath(str(base)))
        except Exception:
            continue
        if not key or key in seen:
            continue
        seen.add(key)
        for pat in _SITE_FFMPEG_PATTERNS:
            hits = sorted(p for p in glob.glob(os.path.join(key, pat))
                          if os.path.isfile(p))
            if hits:
                return hits[0]
    return ""


def find_ffmpeg(allow_import=True):
    """依次尝试：环境变量 FFMPEG → PATH → tools/ffmpeg → .venv 里的 imageio 二进制
    → import imageio-ffmpeg。找不到抛 JobError。"""
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
    cand = _venv_ffmpeg()
    if cand:
        _ffmpeg = cand
        return _ffmpeg
    if allow_import:
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
    p = winproc.run([ff, "-hide_banner", "-i", str(video)],
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


def probe_size_ex(video):
    """探测分辨率，返回 (宽, 高, 原因)。成功时原因为空串。

    失败原因要能直接说给用户听：是找不到 ffmpeg，还是 ffmpeg 读不了这个文件。
    """
    try:
        ff = find_ffmpeg()
    except Exception as e:
        return 0, 0, "找不到 ffmpeg（%s）" % e
    try:
        p = winproc.run([ff, "-hide_banner", "-i", str(video)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, errors="ignore")
    except Exception as e:
        return 0, 0, "ffmpeg 无法启动（%s）" % e
    info = p.stderr or ""
    m = _SIZE_RE.search(info)
    if m:
        return int(m.group(1)), int(m.group(2)), ""
    lines = [ln.strip() for ln in info.splitlines() if ln.strip()]
    tail = lines[-1][:160] if lines else "无输出"
    return 0, 0, "ffmpeg 读不出视频流（%s）" % tail


def probe_size(video):
    """只取分辨率，返回 (宽, 高)；失败返回 (0, 0)。"""
    w, h, _why = probe_size_ex(video)
    return w, h


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
    tmp = tempfile.NamedTemporaryFile(prefix="ppcmd_", suffix=".log", delete=False,
                                          dir=temp_root())
    tmp.close()
    try:
        with open(tmp.name, "wb") as err:
            p = winproc.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=err)
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
    tmp = tempfile.NamedTemporaryFile(prefix="ppcmd_", suffix=".log", delete=False,
                                          dir=temp_root())
    tmp.close()
    p = None
    try:
        with open(tmp.name, "wb") as err:
            p = winproc.popen(cmd, cwd=cwd, env=env,
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
        p = winproc.run([find_ffmpeg(), "-hide_banner", "-encoders"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, errors="ignore")
        if "h264_nvenc" in (p.stdout or ""):
            _encoder = "h264_nvenc"
    except Exception:
        pass
    return _encoder


#: 码率上限用的 bits-per-pixel：crf 越小给得越松（线性插值，两端夹紧）。
#: 实测 4x（3416x1920@30）用 cq14 不限码率 → 58 Mbps，体积是源的 50 倍；
#: 0.09~0.12 bpp 已经看不出差别（PSNR 48 dB 量级），所以按分辨率封顶。
_CAP_BPP = ((14, 0.120), (17, 0.090), (20, 0.065), (23, 0.045), (28, 0.028))


def cap_bpp(crf):
    """crf → 每像素每帧允许的比特数（夹在 0.008~0.18）。"""
    crf = max(0, min(51, int(crf)))
    pts = _CAP_BPP
    if crf <= pts[0][0]:
        bpp = pts[0][1]
    elif crf >= pts[-1][0]:
        bpp = pts[-1][1]
    else:
        bpp = pts[-1][1]
        for (c0, b0), (c1, b1) in zip(pts, pts[1:]):
            if c0 <= crf <= c1:
                bpp = b0 + (b1 - b0) * (crf - c0) / float(c1 - c0)
                break
    return max(0.008, min(0.18, bpp))


def target_maxrate(width, height, fps, crf):
    """按输出分辨率/帧率算码率上限（bit/s）；宽高未知返回 0 = 不限制。"""
    width, height = int(width or 0), int(height or 0)
    if width <= 0 or height <= 0:
        return 0
    fps = float(fps or 0) or 30.0
    rate = width * height * fps * cap_bpp(crf)
    return int(max(1.5e6, min(60e6, rate)))


def mbit(rate):
    """码率显示成 "8.6 Mbps" 这种。"""
    return "%.1f Mbps" % (float(rate) / 1e6)


def video_encode_args(encoder, crf, preset=None, maxrate=0):
    enc = (encoder or "libx264").lower()
    cap = ["-maxrate", str(int(maxrate)), "-bufsize", str(int(maxrate) * 2)] if maxrate else []
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", str(int(crf)), "-b:v", "0"] + cap
    return ["-c:v", "libx264", "-preset", preset or "medium",
            "-crf", str(int(crf))] + cap



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
                  encoder="auto", crf=17, preset=None, emit=None, limit=False,
                  out_size=None):
    """把 frames_dir 下 00000.png 起的序列加上音轨，编码成 out。

    out_size=(w, h) 时先按 lanczos 缩放到这个尺寸再编码（统一输出规格用）；
    只做一次编码，不是"先出一版再转一版"。
    limit=True 时按**最终尺寸**给码率上限（CRF + VBV 封顶）。
    音频优先 copy；mp4 不支持的编码（PCM/Opus）失败后自动退回 AAC 重编一次。
    """
    ff = find_ffmpeg()
    pattern = os.path.join(frames_dir, "%05d.png")
    duration = "%.3f" % (float(n_frames) / float(fps))

    width, height = _first_frame_size(frames_dir)
    final_w, final_h = width, height
    if out_size and int(out_size[0]) > 0 and int(out_size[1]) > 0:
        final_w, final_h = int(out_size[0]), int(out_size[1])
    enc = pick_encoder(encoder)
    # H.264 NVENC 最大 4096；按**缩放后**的尺寸判断
    if enc == "h264_nvenc" and (final_w > NVENC_MAX_SIDE or final_h > NVENC_MAX_SIDE):
        if emit:
            emit.log("[提示] 输出 %dx%d 超过 H.264 NVENC 上限 %d，自动改用 CPU x264 编码"
                     % (final_w, final_h, NVENC_MAX_SIDE))
            emit.log("       想继续用显卡编码，把目标分辨率降一档")
        enc = "libx264"
        preset = preset or "veryfast"
    cap = target_maxrate(final_w, final_h, fps, crf) if limit else 0
    if emit and final_w and final_h:
        resize_note = ""
        if (final_w, final_h) != (width, height) and width and height:
            resize_note = "（从 %dx%d 缩放）" % (width, height)
        emit.log("编码 %dx%d%s · %s · crf %d%s" % (
            final_w, final_h, resize_note, enc, int(crf),
            (" · 码率上限 %s" % mbit(cap)) if cap else ""))

    head = [ff, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "%g" % fps, "-i", pattern, "-i", str(src_video), "-map", "0:v:0"]
    if has_audio:
        head += ["-map", "1:a:0"]
    if (final_w, final_h) != (width, height) and final_w and final_h:
        head += ["-vf", "scale=%d:%d:flags=lanczos" % (final_w, final_h)]
    head += video_encode_args(enc, crf, preset, cap)
    head += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]

    hint = ("若日志里出现 No capable devices found：输出分辨率超过 H.264 NVENC 上限"
            "（宽高需 ≤%d），把编码器改成 CPU x264 或降低超分倍率" % NVENC_MAX_SIDE)

    # 先写同名 .part，成功后再改名：失败/被取消时目标目录不会留下半成品 mp4
    part = out + ".part.mp4"
    try:
        if os.path.exists(part):
            os.remove(part)
    except OSError:
        pass

    def _encode(args):
        try:
            run(args, emit=emit, label="编码")
        except JobError as e:
            try:
                if os.path.exists(part):
                    os.remove(part)
            except OSError:
                pass
            raise JobError(str(e), hint)

    if not has_audio:
        _encode(head + [part])
    else:
        try:
            _encode(head + ["-c:a", "copy", "-t", duration, part])
        except JobError:
            if emit:
                emit.log("音轨无法直接拷贝，改用 AAC 重新编码 ...")
            _encode(head + ["-c:a", "aac", "-b:a", "192k", "-t", duration, part])

    try:
        os.replace(part, out)
    except OSError:
        # 极少数情况（文件被占用）退回直接拷贝
        import shutil as _shutil
        try:
            _shutil.move(part, out)
        except Exception:
            raise JobError("编码完成但无法写入目标文件：%s" % out,
                           "目标文件可能正被播放器占用，关闭后重试")


def scale_video(src, out, size, crf=17, encoder="auto", preset=None, emit=None,
                limit=True):
    """整条视频直接缩放到 size（源已达标、跳过超分时用）。只转一次码。"""
    src, out = str(src), str(out)
    w, h = int(size[0]), int(size[1])
    fps, has_audio, dur = probe(src)
    enc = pick_encoder(encoder)
    if enc == "h264_nvenc" and (w > NVENC_MAX_SIDE or h > NVENC_MAX_SIDE):
        enc = "libx264"
        preset = preset or "veryfast"
    cap = target_maxrate(w, h, fps, crf) if limit else 0
    if emit:
        emit.log("统一尺寸：缩放到 %dx%d · %s · crf %d%s" % (
            w, h, enc, int(crf), (" · 码率上限 %s" % mbit(cap)) if cap else ""))
    cmd = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
           "-i", src, "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "0:a:0"]
    cmd += ["-vf", "scale=%d:%d:flags=lanczos" % (w, h)]
    cmd += video_encode_args(enc, crf, preset, cap)
    cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if has_audio:
        cmd += ["-c:a", "copy"]
    part = out + ".part.mp4"
    try:
        if os.path.exists(part):
            os.remove(part)
    except OSError:
        pass
    try:
        run(cmd + [part], emit=emit, label="缩放")
    except JobError as e:
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        raise JobError(str(e), "缩放失败：目标尺寸可能超出编码器上限，或源文件已损坏")
    try:
        os.replace(part, out)
    except OSError:
        raise JobError("缩放完成但无法写入目标文件：%s" % out,
                       "目标文件可能正被播放器占用，关闭后重试")
    return out


def now():    return time.time()

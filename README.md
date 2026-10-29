# ProPainter 去水印 + 超分 工具箱

把 [ProPainter](https://github.com/sczhou/ProPainter)（视频修复）和 [Real-CUGAN](https://github.com/nihui/realcugan-ncnn-vulkan)（超分）包成了三个双击就能用的 Windows 脚本：

- **去水印**：自动定位角标/水印，逐帧生成掩码，ProPainter 补全后贴回原帧（水印以外的像素不动）
- **超分**：Real-CUGAN 2x/3x/4x，动画线条干净，支持 480p→1080p、1080p→4K
- **一条龙**：先去水印再超分，中间用无损文件，不二次压缩

只处理水印附近的一小块区域，所以 **8 GB 显存的 4060 Ti 也能跑 1080p**，15 秒视频约 5 分钟。

> 上游 ProPainter 的原始说明见 [UPSTREAM_README.md](UPSTREAM_README.md)。

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 / 11 |
| 显卡 | NVIDIA，建议 6 GB 显存以上（8 GB 最稳）；无 N 卡也能跑，但去水印会慢到不可用 |
| Python | 3.9 ~ 3.12（安装时勾选 Add to PATH） |
| 磁盘 | 约 7 GB（虚拟环境 5 GB + 权重 0.2 GB） |
| ffmpeg | 不用手动装，`setup.cmd` 会通过 `imageio-ffmpeg` 自动准备 |

## 安装

双击 **`setup.cmd`**，或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

它会自动完成：建 `.venv` → 装 PyTorch（有 N 卡自动选 CUDA 版）→ 装依赖 →
下 ProPainter 权重（190 MB）→ 下 Real-CUGAN（45 MB）→ 自检。

国内网络慢可以指定镜像：

```powershell
.\setup.ps1 -Mirror https://pypi.tuna.tsinghua.edu.cn/simple
```

## 使用

三个入口，都可以**把 mp4 直接拖上去**：

| 脚本 | 作用 | 输出 |
|---|---|---|
| `去水印.cmd` | 只去水印 | `<名字>_无水印.mp4` |
| `超分.cmd` | 只超分 | `<名字>_2x.mp4` |
| `去水印超分.cmd` | 先去水印再超分 | `<名字>_无水印_2x.mp4` |

命令行用法：

```powershell
.\去水印.cmd "D:\video\a.mp4"                      # 自动找水印
.\去水印.cmd "D:\video\a.mp4" "1314,918,320,120"   # 手动指定水印框 x,y,w,h
.\超分.cmd   "D:\video\a.mp4" 3                    # 3 倍
.\去水印超分.cmd "D:\video\a.mp4" 2                # 去水印 + 2 倍
```

想先确认自动检测准不准：

```powershell
.\.venv\Scripts\python.exe tools\wm_remove.py --video "a.mp4" --auto --dry-run
```
会在视频旁边生成 `<名字>_detect\detect_seg*.jpg`，红框就是识别到的水印。

### 进阶参数

```powershell
# 逐帧掩码（水印会移动时最稳）
python tools\wm_remove.py --video a.mp4 --mask D:\masks        # 掩码目录 00000.png…
# 超分参数
python tools\sr_upscale.py --video a.mp4 --scale 3 --denoise 3 --model models-pro
# 一条龙 + 指定水印框
python tools\pipeline.py --video a.mp4 --scale 2 --rect 1314,918,320,120
```

`--denoise`：`-1` 不降噪、`0` 保守、`1~3` 递增强度。不给则自动（高度 <720 用 3，否则 0）。

## 常见问题

**Q：水印没擦干净？**
自动模式只认浅色角标。深色水印、满屏浮水印、贴在图正中的，请用 `--rect x,y,w,h` 指定。
不确定坐标就先用 `--dry-run` 看预览图。

**Q：输出时长变短 / 画面变少？**
旧版 `-shortest` 会在音轨时间戳异常的片源上截断画面，现已改为按帧数精确截断。
如果还遇到，脚本会打印 `[警告] 输出时长 x != 预期 y`，把这条信息贴出来即可。

**Q：跑起来像幻灯片 / 卡在推理？**
显存碎片。脚本已自动设置 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`，
若仍卡，降低 `--subvideo`（默认 40，试 20）。

**Q：超分后人脸/线条变糊？**
降噪过头。1080p 这类已干净的源用 `--denoise 0`；只有 480p 老片才用 `3`。

**Q：显存不够（CUDA out of memory）？**
去水印只处理水印附近区域，一般不会 OOM。真遇到把 `--padding` 从 0.45 降到 0.3。

## 原理

去水印：抽帧 → 自动检测（白色角标候选聚类 + 多尺度模板匹配逐帧跟踪）→ 按位置切段 →
每段按水印框外扩裁剪 → 生成逐帧掩码 → ProPainter 补全 → 羽化贴回 → 重新编码拼音轨。

超分：抽帧 → Real-CUGAN 放大 → 按帧数精确截断 → 编码拼音轨。

## 目录

```
├─ tools/                 # 本项目的脚本
│  ├─ common.py           # 路径 / ffmpeg / 进程 工具
│  ├─ wm_remove.py        # 去水印
│  ├─ sr_upscale.py       # 超分
│  └─ pipeline.py         # 一条龙
├─ setup.cmd / setup.ps1  # 一键安装
├─ 去水印.cmd / 超分.cmd / 去水印超分.cmd
├─ model/ core/ utils/ …  # ProPainter 上游代码
└─ weights/               # setup 时自动下载（不入库）
```

## 许可

- 本仓库的胶水脚本（`tools/`、`*.cmd`、`setup.*`）：MIT
- ProPainter 及其权重：**S-Lab License 1.0，仅限非商业用途**，商用请联系原作者
- Real-CUGAN / realcugan-ncnn-vulkan：MIT
- Real-ESRGAN：BSD-3-Clause

详见 [THIRD_PARTY.md](THIRD_PARTY.md)。请勿将本工具用于去除他人版权水印等侵权用途。

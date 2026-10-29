# ProPainter 视频去水印 / 超分 工具箱

把 [ProPainter](https://github.com/sczhou/ProPainter)（视频修复）和 [Real-CUGAN](https://github.com/nihui/realcugan-ncnn-vulkan)（超分）包成了三个双击就能用的 Windows 脚本：

| 入口 | 作用 | 输出 |
|---|---|---|
| `去水印.cmd` | 只去水印 | `<名字>_无水印.mp4` |
| `超分.cmd` | 只超分 | `<名字>_2x.mp4` |
| `去水印超分.cmd` | 先去水印再超分 | `<名字>_无水印_2x.mp4` |

三个脚本都支持把 mp4 **直接拖上去**，也支持透传命令行参数（见下文）。

## 环境要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 10 1803+ / Windows 11（需要自带的 `tar` 与 `curl`） |
| 显卡 | NVIDIA，建议 6 GB 显存以上（8 GB 最稳）；无 N 卡也能跑，但去水印会慢到不可用 |
| 驱动 | cu121 需要 **527.41 或更新**（`setup.ps1` 会自动检测，太旧则退回 CPU 版） |
| Python | 3.9 ~ 3.12；**没有也能装**，`setup.ps1` 会自动下载便携版到 `tools\python\` |
| 磁盘 | 约 7-8 GB（虚拟环境 5-6 GB + 权重 0.2 GB + 临时帧） |
| ffmpeg | 不用手动装，由 `imageio-ffmpeg` 提供 |

## 安装

双击 **`setup.cmd`**，或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

流程：预检（磁盘 / Python / 驱动）→ 建 `.venv` → 装 PyTorch（有 N 卡自动选 CUDA 版）→ 装依赖 → 下 ProPainter 权重（190 MB）→ 下 Real-CUGAN（45 MB）→ 自检。

几个要点：

- **失败会给出退出码和日志**：全过程写在 `setup.log`，失败时窗口会停住并提示看日志。
- **可以反复重跑**：已完成的步骤（`.venv`、权重、Real-CUGAN）会自动跳过，中断后重新双击即可续装。
- **下载不会留下半截文件**：先写 `.part`，校验大小后才落盘；直连失败会自动换 `gh-proxy` / `ghfast` 镜像。
- 国内网络慢可以指定镜像：

```powershell
.\setup.ps1 -Mirror https://pypi.tuna.tsinghua.edu.cn/simple
```

- 想强制重装某个环节：`.\setup.ps1 -Force`。

## 使用

```powershell
.\去水印.cmd "D:\video\a.mp4"                              # 自动找水印
.\去水印.cmd "D:\video\a.mp4" --rect 1314,918,320,120      # 手动指定水印框 x,y,w,h
.\去水印.cmd "D:\video\a.mp4" --dry-run                    # 只检测 + 出预览图（秒级）
.\去水印.cmd "D:\video\a.mp4" --mask D:\masks              # 逐帧掩码
.\超分.cmd   "D:\video\a.mp4" 3                            # 3 倍
.\去水印超分.cmd "D:\video\a.mp4" 2 --rect 1314,918,320,120
```

想先确认自动检测准不准，用 `--dry-run`（**秒级**，只抽 12 张采样帧，不再为看几张图抽整片）：

```powershell
.\.venv\Scripts\python.exe tools\wm_remove.py --video "a.mp4" --auto --dry-run
```

会在视频旁边生成 `<名字>_detect_<时间戳>\detect_seg*.jpg`，红框就是识别到的水印。

### 常用参数（三个脚本通用）

| 参数 | 说明 |
|---|---|
| `--encoder auto\|nvenc\|x264` | 默认 `auto`：有 NVENC 用硬件编码（快 5-10 倍），否则 x264 |
| `--crf N` | 输出画质，默认 17；越小越清晰、文件越大 |
| `--log-file "D:\pp.log"` | 把完整日志同时写进文件，排障时贴这个 |
| `--workdir "E:\tmp"` | 临时帧放哪；默认系统临时目录，**C 盘紧张时务必改到 D/E 盘** |
| `--keep` | 保留中间文件（默认成功后自动删） |

去水印额外支持：`--padding`（水印框外扩比例，默认 0.45）、`--subvideo`（默认 40，OOM 时降到 20）、`--neighbor`、`--ref-stride`、`--mask-dilation`、`--detect-thr`（默认 0.62）、`--detect-fill`（白色填充率上限，默认 0.60，粗体/密集文字水印可试 0.85）、`--detect-aspect`（候选宽高比上限，默认 10）。

> 自动检测的默认值已按"文字型水印"调过：同一行里分开的字符合并成一个候选（形态学闭运算 13 px），填充率改用闭运算之前的掩码来算，否则粗体字会被误判成"实心色块"。检测不到时它会提示改用 `--rect`，并给出 `--detect-fill` 的建议值。

超分额外支持：`--scale 2\|3\|4`、`--denoise -1\|0\|1\|2\|3`、`--model models-pro\|models-se`。

一条龙额外支持：`--rect`、`--denoise`、`--intermediate-crf`（默认 12；旧版是无损 0，1080p 一分钟能到 2 GB）。

## 常见问题

**Q：水印没擦干净？**
自动模式只认浅色角标。深色水印、满屏浮水印、贴在图正中的，请用 `--rect x,y,w,h` 指定；不确定坐标就 `--dry-run` 看预览图。半透明/彩色 logo 可以调 `--detect-thr` 或直接上 `--mask`。

**Q：输出时长变短 / 画面变少？**
旧版 `-shortest` 会在音轨时间戳异常的片源上截断画面，现已改为按帧数精确截断。如果还遇到，脚本会打印 `[警告] 输出时长 x != 预期 y`，把这条贴上即可。

**Q：跑起来像幻灯片 / 卡在推理？**
先确认真的在用 GPU：日志里 `cuda True` 才是；`setup.log` 里 `PyTorch: cpu` 说明驱动太旧被降级了。
显存吃紧时把 `--subvideo` 从 40 降到 20；显存碎片严重时再设环境变量 `PP_EMPTY_CACHE=1` 恢复旧的“每轮清缓存”行为（更慢但更省）。

**Q：超分后人脸/线条变糊？**
降噪过头。1080p 这类已干净的源用 `--denoise 0`；只有 480p 老片才用 `3`。

**Q：显存不够（CUDA out of memory）？**
去水印只处理水印附近区域，一般不会 OOM。真遇到把 `--padding` 从 0.45 降到 0.3，或降 `--subvideo`。

**Q：装到一半断了怎么办？**
直接重新双击 `setup.cmd`。它会跳过已装好的部分，并清理上次的 `.part` 残留。

## 原理

去水印：抽帧 → 自动检测（白色角标候选聚类 + 多尺度模板匹配逐帧跟踪）→ 按位置切段 →
每段按水印框外扩裁剪 → 生成逐帧掩码 → ProPainter 补全 → 羽化贴回 → 重新编码拼音轨。

超分：抽帧 → Real-CUGAN 放大 → 按帧数精确截断 → 编码拼音轨。

## 目录

```
├─ tools/                 # 本项目的脚本
│  ├─ common.py           # 路径 / 日志 / ffmpeg / 子进程 / 编码参数
│  ├─ wm_remove.py        # 去水印
│  ├─ sr_upscale.py       # 超分
│  └─ pipeline.py         # 一条龙
├─ tests/                 # 纯 CPU 单测（python -m unittest discover -s tests）
├─ setup.cmd / setup.ps1  # 一键安装
├─ env.cmd                # 三个入口共用的环境变量
├─ 去水印.cmd / 超分.cmd / 去水印超分.cmd
├─ model/ core/ utils/ …  # ProPainter 上游代码
└─ weights/               # setup 时自动下载（不入库）
```

## 自检 / 单测

```powershell
.\.venv\Scripts\python.exe -c "import torch,cv2,scipy,imageio,timm;print(torch.__version__, torch.cuda.is_available())"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 许可

- 本仓库的胶水脚本（`tools/`、`tests/`、`*.cmd`、`setup.*`）：MIT
- ProPainter 及其权重：**S-Lab License 1.0，仅限非商业用途**，商用请联系原作者
- Real-CUGAN / realcugan-ncnn-vulkan：MIT
- Real-ESRGAN：BSD-3-Clause

详见 [THIRD_PARTY.md](THIRD_PARTY.md)。请勿将本工具用于去除他人版权水印等侵权用途。

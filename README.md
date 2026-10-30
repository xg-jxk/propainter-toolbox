# ProPainter 视频修复工具箱

> 把 [ProPainter](https://github.com/sczhou/ProPainter)（视频修复/补全）和
> [Real-CUGAN](https://github.com/nihui/realcugan-ncnn-vulkan)（超分）包成一个
> **Windows 桌面应用 + 三个拖拽脚本**，全程本地运行，不上传云端。

> **使用范围（重要）**
> 本工具用于修复**你拥有版权、或已获得授权**的视频画面（例如清理自己素材上的字幕条、台标、杂物、角标）。
> 请勿用于去除他人作品的署名/权利管理信息，或用于搬运、二次分发他人内容——那属于侵权，责任自负。
> 完整条款见 [TERMS.md](TERMS.md)。

> **下载**：
> - GitHub：<https://github.com/xg-jxk/propainter-toolbox/releases/latest>
> - Gitee 镜像：<https://gitee.com/jiang-xinkai/propainter-toolbox/releases/tag/v1.3.2>
>
> 便携包 `ProPainterToolbox-<版本>-portable.zip`，约 49 MB；解压即用，首次启动会引导安装运行时。

---

## 1. 项目介绍

### 1.1 这是什么

一个 Windows 上的视频处理工具，解决两件事：

- **区域修复**：把画面中指定的一块区域（字幕条、台标、角标、杂物、镜头污点）抹掉，并用前后帧的内容补全。
  底层是 ProPainter 的视频补全模型，工具负责抽帧、定位、裁剪、生成掩码、贴回、拼音轨这一整条链路。
- **超分**：把低分辨率视频放大 2/3/4 倍，底层是 Real-CUGAN 的 ncnn 实现（Vulkan，不依赖 CUDA）。

两种能力可以单独用，也可以串起来（先修复再超分），一条命令跑完。

### 1.2 能做什么

| 模式 | 输入 | 输出 | 典型场景 |
|---|---|---|---|
| 区域修复 | mp4 / mov / mkv 等 | `<名字>_已修复.mp4` | 清理自有素材上的字幕条、台标、角标、杂物 |
| 超分 | 同上 | `<名字>_2x.mp4` | 老片、录屏、压缩过的素材放大 |
| 区域修复 + 超分 | 同上 | `<名字>_已修复_2x.mp4` | 先修干净再放大，成片直接可用 |

支持的格式：`mp4 / mov / avi / mkv / webm / m4v / ts / flv / wmv / mpg`。
音轨会自动保留（直接拷贝；遇到 mp4 不支持的编码会自动转 AAC）。
输出时长按帧数精确截断，不会因为音轨时间戳异常而变短。

### 1.3 系统要求

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | Windows 10 1803+ / Windows 11 | 需要系统自带的 `tar` 与 `curl` |
| 显卡 | NVIDIA，建议 ≥ 6 GB 显存 | RTX 20/30/40 系均可；无 N 卡能跑但极慢 |
| 驱动 | **≥ 527.41** | 低于此版本 `setup.ps1` 会自动退回 CPU 版 |
| 磁盘 | ≥ 8 GB 空闲 | 运行时约 2.5 GB + 临时帧（长视频更占） |
| 网络 | 首次安装需要联网 | 装完后可离线使用 |
| 权限 | 安装目录可写 | **不要**放 `C:\Program Files` |

### 1.4 它怎么工作

```
区域修复：抽帧 → 自动/手动定位目标区域 → 按位置切段 → 分段裁剪
        → 生成逐帧掩码 → ProPainter 补全 → 羽化贴回原帧 → 编码并保留音轨
超分：    抽帧 → Real-CUGAN 放大 → 按帧数精确截断 → 编码并保留音轨
```

这也解释了为什么首次要下载约 2.5 GB：PyTorch（CUDA 版）+ 三个模型权重（190 MB）+ 超分工具。
程序只处理目标区域附近的裁片，所以显存占用和耗时都远小于整帧修复。

### 1.5 目录结构

```
ProPainterToolbox\
├─ ProPainterToolbox.exe     # 桌面应用（双击这个）
├─ 首次使用.txt              # 给接收方看的一页说明
├─ _internal\                # 应用依赖（PySide6 等，别删）
├─ pplib\                    # 核心流程（修复/超分/任务编排）
├─ tools\                    # 命令行脚本（区域修复/超分/一条龙）
├─ model\ core\ utils\ RAFT\ # ProPainter 上游推理代码
├─ inference_propainter.py   # 推理入口（被 tools 调用）
├─ setup.ps1 / setup.cmd     # 运行时安装脚本（应用里点“安装运行时”就是跑它）
├─ 区域修复.cmd / 超分.cmd / 修复超分.cmd
├─ README.md / TERMS.md / THIRD_PARTY.md
├─ .venv\                    # 首次安装后生成（Python 环境，约 2.5 GB）
├─ weights\                  # 首次安装后生成（模型权重）
└─ tools\realcugan\          # 首次安装后生成（超分工具）
```

> `.venv` 里记录的是**绝对路径**，所以装好之后不要直接剪切/移动整个文件夹（见 3.1）。

### 1.6 版本与许可

- 当前版本：**v1.3.2**
- 技术栈：Python 3.11 + PyTorch 2.5.1 (CUDA 12.1) + PySide6 6.9 + ffmpeg（imageio-ffmpeg 自带）
- 许可：
  - 本仓库胶水代码（`pplib/`、`app/`、`tools/`、`build/`、`tests/`、`*.cmd`、`setup.*`）：**MIT**
  - **ProPainter 及其权重：S-Lab License 1.0，仅限非商业用途**（商用请联系原作者）
  - Real-CUGAN / realcugan-ncnn-vulkan：MIT
- 详见 [TERMS.md](TERMS.md) 与 [THIRD_PARTY.md](THIRD_PARTY.md)

---

## 2. 安装使用步骤

> **三条路线，对号入座：**
>
> | 你的情况 | 走哪条 | 耗时 |
> |---|---|---|
> | 只想用，不想碰命令行 / Python | **2.1 便携版** | 下载 1 分钟 + 首次装运行时 10~30 分钟 |
> | 已有 Python，想改代码 | **2.2 源码方式** | 10~20 分钟 |
> | 想自己打包发布 | **2.5 开发者打包** | 5 分钟 |

### 2.1 路线 A：便携版（推荐，不需要装 Python）

#### 第 1 步：下载

1. 直接打开最新版页面：<https://github.com/xg-jxk/propainter-toolbox/releases/latest>
   （从仓库首页进的话：右侧栏的 **Releases** 区块 → 最新版本；它**不在**顶部 `Code / Issues` 那一排）
2. 在 **Assets** 里下载 **`ProPainterToolbox-1.3.2-portable.zip`**（约 **49 MB**）
3. Gitee 镜像（**同一份文件**）：<https://gitee.com/jiang-xinkai/propainter-toolbox/releases/tag/v1.3.2>
   国内下载 GitHub 慢时用它，附件名与校验值都一致

> 包很小是因为它只是“界面外壳”：PyTorch、模型权重、超分工具都在第一次运行时按需下载。
> 若 Releases 里暂时没有附件，请走 2.2 源码方式，或联系作者。

#### 第 2 步：解压

1. 右键 zip → **全部解压缩**（Windows 自带即可，不用装 WinRAR）
2. 解压到有空间的磁盘，例如 `D:\ProPainterToolbox`
   - ✅ 推荐：`D:\`、`E:\` 等数据盘
   - ❌ 不要：`C:\Program Files`（写入受限，安装运行时会失败）
   - 路径含中文、空格都没问题（已适配）
3. 确认目录里能看到：`ProPainterToolbox.exe`、`_internal\`、`tools\`、`首次使用.txt`
   **别只把 exe 单独拖出来**——它依赖同目录的 `_internal\` 和 `tools\`

#### 第 3 步：第一次启动

1. 双击 **`ProPainterToolbox.exe`**
2. 若弹出「Windows 已保护你的电脑」（SmartScreen）：
   点 **更多信息 → 仍要运行**（exe 未做代码签名，属正常现象）
3. 首次会弹出**使用条款**：滚动读完 → 勾选「我已阅读并同意…」→ **同意并继续**
   （不同意就点「退出」，程序直接关闭）
4. 进入主界面。此时顶部大概率是红字：
   `缺少运行时：Python 虚拟环境、ProPainter 权重、Real-CUGAN`
   —— **这是正常的**，下一步安装即可。

#### 第 4 步：安装运行时（只需一次）

1. 点顶部红色状态条旁边的 **【安装运行时】**
2. 弹窗会实时滚日志，依次执行：

   | 阶段 | 内容 | 体积 | 大致耗时（百兆宽带） |
   |---|---|---|---|
   | 预检 | 磁盘空间、Python、显卡驱动 | — | 秒级 |
   | 建环境 | 缺 Python 时下载便携版 3.11 + 建 `.venv` | ~100 MB | 1~3 分钟 |
   | 装 PyTorch | `torch 2.5.1+cu121` + `torchvision`（N 卡）或 CPU 版 | ~2.4 GB | 5~20 分钟 |
   | 装依赖 | opencv / scipy / imageio-ffmpeg / timm 等 | ~300 MB | 1~3 分钟 |
   | 下权重 | `raft-things` / `recurrent_flow_completion` / `ProPainter` | ~190 MB | 1~5 分钟 |
   | 下超分 | Real-CUGAN ncnn 版 | ~45 MB | 1 分钟 |
   | 自检 | 实际 `import torch` + 检查依赖完整性 | — | 秒级 |

3. **可以最小化去干别的**，但别关机；期间不要移动/删除安装目录
4. 成功时窗口显示 **安装完成 ✔**；关掉向导，顶部变绿：
   `运行时就绪 · NVIDIA GeForce RTX 4060 Ti（驱动 616.92）`
5. 失败时：先看窗口最后几行，详细日志在安装目录的 **`setup.log`**；
   修好后**再点一次**【安装运行时】，已完成步骤会自动跳过（不会重下 2.4 GB）

> 国内网络：`setup.ps1` 自带三源重试（直连 → gh-proxy → ghfast），pip 失败会自动切清华镜像。
> 想手动指定镜像：`powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1 -Mirror https://pypi.tuna.tsinghua.edu.cn/simple`

#### 第 5 步：处理第一个视频

1. **加文件**：把 mp4 **拖进虚线框**，或点「添加文件…」
   一次最多 **20 个**，超出会弹窗告诉你哪些没加进去
2. **选模式**（「模式」下拉）：
   - `区域修复` —— 只去掉画面里的东西
   - `超分` —— 只放大
   - `区域修复 + 超分` —— 先修再放大
3. **设区域位置**（只在区域修复类模式生效）：
   - `自动定位`（默认）—— 自动找浅色角标/文字，日志会打印定位框
   - `手动矩形` —— 自己填 `x,y,w,h`，例如 `1314,918,320,120`（最可靠）
   - `逐帧掩码` —— 选掩码目录（每帧一张 png）或单张掩码
4. **参数先保持默认**：外扩 0.45、分段 40、画质 17、编码器 auto
5. 点 **【开始处理】**
   - 队列**串行**跑（GPU 并行只会爆显存）
   - 进度条是**逐帧真实进度**，状态栏显示 `当前/总数 · 剩余时间`
   - 想中途停：点 **【取消】**，几秒内结束推理进程并清理临时文件
6. 完成后会自动打开输出目录（可关掉「完成后打开输出目录」）

#### 第 6 步：找输出文件

- 默认写在**源视频所在目录**：
  - 区域修复 → `<名字>_已修复.mp4`
  - 超分 → `<名字>_2x.mp4`（3x / 4x 对应改名）
  - 一条龙 → `<名字>_已修复_2x.mp4`
- 重名自动加 `(2)`、`(3)`，不会覆盖已有文件
- 想统一输出到某个盘：在「输出目录」里选路径
- 也可以随时点 **【打开输出目录】**

### 2.2 路线 B：从源码运行（已有 Python 3.9~3.12）

1. 下载源码（`git clone` 或 Release 里的 Source code zip）并解压
2. 双击 **`setup.cmd`** —— 同样会建 `.venv`、装依赖、下权重（10~20 分钟）
   国内网络可先指定镜像：`setup.cmd -Mirror https://pypi.tuna.tsinghua.edu.cn/simple`
3. 之后两种用法：
   - **命令行**：直接双击 `区域修复.cmd` / `超分.cmd` / `修复超分.cmd`（把视频拖上去即可）
   - **界面**：先 `.\.venv\Scripts\python.exe -m pip install PySide6`，然后
     `.\.venv\Scripts\pythonw.exe -m app`

源码方式不需要打包 exe，改代码即时生效。

### 2.3 界面说明

| 区域 | 内容 |
|---|---|
| 顶部 | 标题 + 运行时状态（显卡/驱动）+ GitHub 入口 + 使用条款 + 环境信息 |
| 虚线框 | 拖拽区，也可点击选择文件 |
| 待处理队列 | 文件 / 状态 / 进度 / 用时 / 输出；可移除选中、清空 |
| 右侧设置 | 预设（快速 / 平衡 / 高质量）+「区域修复」「超分」两张开关卡片 + 共用「输出」卡片；每个参数旁的 **i** 悬停可看说明，高级参数默认收起 |
| 进度行 | 开始 / 取消 / 打开输出目录 + 进度条 + 状态文字 |
| 日志区 | 实时日志（等同命令行输出） |
| 【使用条款】 | 随时重看条款 |
| 【环境信息】 | torch 版本、CUDA 是否可用、NVENC、权重是否齐全 |

### 2.4 命令行 / 拖拽脚本

三个 `.cmd` 都可以**把视频拖上去**，也可以带参数：

```powershell
.\区域修复.cmd "D:\video\a.mp4"                              # 自动定位
.\区域修复.cmd "D:\video\a.mp4" --rect 1314,918,320,120      # 手动指定区域
.\区域修复.cmd "D:\video\a.mp4" --auto --dry-run             # 只看检测结果（秒级）
.\区域修复.cmd "D:\video\a.mp4" --mask D:\masks              # 逐帧掩码
.\超分.cmd    "D:\video\a.mp4" 3                             # 3 倍
.\修复超分.cmd "D:\video\a.mp4" 2 --rect 1314,918,320,120
```

直接调 Python（等价，参数更全）：

```powershell
.\.venv\Scripts\python.exe tools\region_repair.py --video "a.mp4" --auto --dry-run
.\.venv\Scripts\python.exe tools\sr_upscale.py --video "a.mp4" --scale 3 --denoise 3
.\.venv\Scripts\python.exe tools\pipeline.py --video "a.mp4" --scale 2 --rect 1314,918,320,120
```

`--dry-run` 只抽 12 张采样帧做定位（**秒级**），会在视频旁生成
`<名字>_detect_<时间戳>\detect_seg*.jpg`，红框就是识别到的区域——不确定坐标时先用它。

#### 参数速查

| 参数 | 适用 | 说明 |
|---|---|---|
| `--encoder auto\|nvenc\|x264` | 全部 | 默认 auto：有 NVENC 用硬件编码（快 5~10 倍） |
| `--crf N` | 全部 | 画质，默认 17；越小越清晰、文件越大 |
| `--log-file "D:\pp.log"` | 全部 | 完整日志同时写文件，排障时贴这个 |
| `--keep` | 全部 | 保留中间文件（默认成功后删除） |
| `--padding 0.45` | 修复 | 目标框外扩比例；残影多就加大，糊了就减小 |
| `--subvideo 40` | 修复 | 分段长度；显存不足降到 20 |
| `--neighbor 10` | 修复 | 局部邻域帧数 |
| `--ref-stride 12` | 修复 | 全局参考帧步长 |
| `--mask-dilation 2` | 修复 | 掩码膨胀像素 |
| `--detect-thr 0.62` | 修复(自动) | 逐帧匹配阈值 |
| `--detect-fill 0.85` | 修复(自动) | 白色填充率上限，粗体字定位不到时可试 |
| `--detect-aspect 10` | 修复(自动) | 候选宽高比上限 |
| `--scale 2\|3\|4` | 超分 | 放大倍数 |
| `--denoise -1\|0\|1\|2\|3` | 超分 | 降噪强度；不给则按高度自动（<720 用 3） |
| `--model models-pro\|models-se` | 超分 | 超分模型 |
| `--intermediate-crf 12` | 一条龙 | 中间文件码率（0 为无损，但文件巨大） |
| `--workdir "E:\tmp"` | 全部（CLI） | 临时帧放大盘，避免撑爆 C 盘 |

### 2.5 开发者：测试与打包

```powershell
# 单测（37 项，纯 CPU，不需要显卡）
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 打包 GUI 外壳 + 便携 zip
powershell -NoProfile -ExecutionPolicy Bypass -File build\make.ps1 -Zip
# 产物：dist\ProPainterToolbox\ProPainterToolbox.exe
#       dist\ProPainterToolbox-1.3.2-portable.zip

# 再打安装包（需装 Inno Setup）
ISCC.exe build\installer.iss
# 产物：build\out\ProPainterToolbox-Setup-1.3.2.exe
```

> 推 `v*` 标签会自动触发 GitHub Actions（`.github/workflows/release.yml`）完成打包并发布 Release，
> 本地不需要出包；也可以手动运行 `make.ps1` 只出 exe 自测。
>
> 完整发布步骤（GitHub 自动 + Gitee 手动、两个 API 坑、发版清单）见 **[docs/RELEASE.md](docs/RELEASE.md)**。

要点：**只打包 GUI 外壳**（PySide6，约 110 MB），不打包 torch/cv2；运行期通过 `PP_ROOT`
定位 `.venv` / `weights`，所以换机器后首次启动仍会引导在线安装。

### 2.6 卸载与清理

1. 直接删除程序目录（`.venv`、`weights`、`tools\realcugan` 都在里面，会一并删掉）
2. 删除配置与日志：`%LOCALAPPDATA%\ProPainterToolbox\`
3. 用 Inno 安装包装的，走「设置 → 应用 → 卸载」同样会清理

---

## 3. 常见问题

### 3.1 安装相关

**Q：双击没反应 / 一闪就没 / 杀毒软件报毒？**
exe 用 PyInstaller 打包且未签名，Defender 或国产杀软常误报。把解压目录加进白名单，
或先关掉实时防护再解压。不要从 `_internal` 里单独运行 DLL。

**Q：SmartScreen 提示“Windows 已保护你的电脑”？**
点「更多信息 → 仍要运行」。要彻底消除只能买代码签名证书。

**Q：点【安装运行时】报错 / 中途退出？**
看安装目录的 `setup.log` 最后几十行，常见三类：
- 磁盘不足（需 ≥ 8 GB，清理后重试）
- 网络超时（换个时间，或手动指定镜像重试）
- 驱动过旧（升级到 527.41+ 后重试；或让它退回 CPU 版）

重试时会自动跳过已完成步骤，**不会**重下 2.4 GB 的 PyTorch。

**Q：能装到 `C:\Program Files` 吗？**
不建议。那里写入需要管理员权限，安装运行时会在建 `.venv` 时失败。放 `D:\` 之类的数据盘。

**Q：能完全不联网安装吗？**
目前不行：PyTorch + 权重约 2.5 GB，首次安装必须联网。
另外 `.venv` 里是绝对路径，**不能**把别人装好的目录直接拷来用——换机器请重新点「安装运行时」。

**Q：装好后把文件夹移到别的盘，就打不开了？**
`.venv` 记录了绝对路径。移动后请重新点【安装运行时】（会快速重建），或把目录移回原位。

**Q：Gitee 和 GitHub 装哪个？**
代码一致，随便。国内下载 GitHub 慢就用 Gitee 镜像。

### 3.2 使用相关

**Q：支持哪些格式？音轨会丢吗？**
`mp4 / mov / avi / mkv / webm / m4v / ts / flv / wmv / mpg`。音轨保留（直接拷贝；
mp4 不支持的编码会自动转 AAC 192k）。输出统一 `yuv420p`，兼容性最好。

**Q：能一次拖 100 个吗？**
界面限 20 个（GPU 串行跑，多了只是排队更久）。命令行没有这个限制。

**Q：处理到一半关窗口会怎样？**
会提示确认；确认后结束当前任务并清理临时目录。已完成的文件不受影响。

**Q：输出为什么和源文件一样大 / 更大？**
默认 `crf 17` 偏高质量。想小一点把 `crf` 调到 20~23（画质略降）。

**Q：能同时开两个窗口吗？**
不能，单实例保护（同时跑会抢显存）。

### 3.3 效果与性能

**Q：自动定位找不到目标？**
自动模式只认**浅色**角标/文字。先用 `--dry-run` 看预览图；不行就：
- 用「手动矩形」直接给 `x,y,w,h`（最可靠）
- 或调 `--detect-fill 0.85`、`--detect-aspect 12`
- 或用「逐帧掩码」

**Q：修完还有残影 / 边缘发糊？**
- 残影：把 `padding` 从 0.45 提到 0.6，让模型有更多上下文
- 发糊：把 `padding` 降到 0.3；或把矩形收紧到刚好包住目标
- 目标在快速移动：用逐帧掩码最稳

**Q：修完运动物体变形了？**
区域修复本质是“用前后帧内容补洞”，目标区域里有大的运动物体会露馅。缩小区域、或用逐帧掩码限定范围。

**Q：跑起来像幻灯片？**
先确认真的在用 GPU：日志里应是 `cuda True`；`setup.log` 里 `PyTorch: cpu` 说明驱动太旧被降级了。
无 N 卡时区域修复基本不可用（十几秒一帧），建议只用超分。

**Q：显存不够（CUDA out of memory）？**
把「分段 subvideo」从 40 降到 20，`padding` 降到 0.3；仍不行就设环境变量
`PP_EMPTY_CACHE=1` 恢复旧的“每轮清缓存”行为（更慢但更省）。

**Q：C 盘被临时帧撑爆？**
命令行加 `--workdir "E:\tmp"` 指定到大盘（界面暂未暴露该选项，可用命令行跑）。

**Q：超分后人脸、线条变糊？**
降噪过头。1080p 这类干净源用 `--denoise 0`；只有 480p 老片才用 `3`。

**Q：输出时长变短 / 画面少了？**
已改为按帧数精确截断（不再用 `-shortest`）。如果还遇到，脚本会打印
`[警告] 输出时长 x != 预期 y`，把这条和 `--log-file` 的日志一起反馈。

### 3.4 合规与许可

**Q：能去掉别人视频的水印吗？**
**不能。** 去除他人作品的署名/权利管理信息属于侵权；工具条款明确禁止此类用途（见 [TERMS.md](TERMS.md)）。

**Q：能商用吗？**
胶水代码是 MIT，但 **ProPainter 权重是 S-Lab License 1.0，仅限非商业**。商用请联系 ProPainter 作者授权。

**Q：我自己拍的视频，能去掉自己加的字幕/台标吗？**
可以，这正是设计用途。

### 3.5 出问题时怎么反馈

附带这些信息能大幅加快定位（不含隐私内容）：

1. 界面日志或 `--log-file` 的日志文件
2. `setup.log`（安装 / 环境问题）
3. 【环境信息】里的 torch 版本、`cuda` 是否可用、显卡与驱动版本
4. 视频的分辨率、帧率、时长，以及用的参数（模式、是否手动矩形）

提 issue：<https://github.com/xg-jxk/propainter-toolbox/issues>（或 Gitee 的 Issues）

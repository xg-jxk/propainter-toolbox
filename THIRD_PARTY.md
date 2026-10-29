# 第三方组件与许可

本项目是 [ProPainter](https://github.com/sczhou/ProPainter) 和
[Real-CUGAN](https://github.com/nihui/realcugan-ncnn-vulkan) 的封装脚本，不含任何自研模型。

## ProPainter

- 仓库：https://github.com/sczhou/ProPainter
- 论文：ProPainter: Improving Propagation and Transformer for Video Inpainting (ICCV 2023)
- 许可：**S-Lab License 1.0**（见 `LICENSE`）
- 关键限制：**仅限非商业用途**。允许在保留版权声明、许可证全文与免责声明的前提下，
  以源码或二进制形式再分发（非商业）。
- 商用授权请联系：Shangchen Zhou <shangchenzhou@gmail.com>、Chen Change Loy <ccloy@ntu.edu.sg>
- 权重文件（`ProPainter.pth` / `recurrent_flow_completion.pth` / `raft-things.pth`）
  由 `setup.ps1` 从官方 Release 下载，**不随本仓库分发**。

## Real-CUGAN / realcugan-ncnn-vulkan

- 仓库：https://github.com/nihui/realcugan-ncnn-vulkan
- 算法：https://github.com/bilibili/ailab（Real-CUGAN）
- 许可：MIT
- 二进制由 `setup.ps1` 从官方 Release 下载，**不随本仓库分发**

## Real-ESRGAN（可选）

- 仓库：https://github.com/xinntao/Real-ESRGAN
- 许可：BSD-3-Clause
- 本项目未强制依赖；如需实拍素材超分，可自行下载 `realesrgan-ncnn-vulkan`。

## FFmpeg

- 本项目不打包 ffmpeg。运行时依次查找：环境变量 `FFMPEG` → PATH → `tools/ffmpeg/` →
  `imageio-ffmpeg` 自带的构建。
- ffmpeg 为 GPL/LGPL 许可，若自行分发请遵守其条款。

## 免责声明

本工具仅用于处理你拥有版权或已获授权的素材。用于去除他人作品的水印可能构成侵权，
由此产生的责任由使用者自行承担。

# 杀软排除目录（让处理与构建不被实时扫描拖慢）

视频处理会短时间写入大量帧文件（1080p 一部长片约 1~2 GB），
实时防护逐个扫描会明显拖慢甚至卡顿。把下面 **两个目录** 加入信任区即可。

## 需要排除的路径

| 路径 | 内容 |
|---|---|
| `E:\propainter-toolbox-main` | 程序、模型权重、便携 Python、构建产物 |
| `%LOCALAPPDATA%\ProPainterToolbox` | 配置、日志、**全部临时文件**（`temp\` 子目录） |

展开后的第二条通常是：

```
C:\Users\<你的用户名>\AppData\Local\ProPainterToolbox
```

> 从 v1.3.29 起，所有中间帧、切片、编码日志都放在
> `%LOCALAPPDATA%\ProPainterToolbox\temp`，不再散落在系统 `%TEMP%`，
> 因此只排除这一个目录即可，不必把整个 `%TEMP%` 加白。

## 火绒

1. 打开火绒 → **防护中心** → 右上角 **设置**
2. 左侧 **信任区** → **添加目录**
3. 依次添加上述两个目录
4. 确定保存（不需要重启）

## Windows Defender（如果启用）

管理员 PowerShell：

```powershell
Add-MpPreference -ExclusionPath "E:\propainter-toolbox-main"
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\ProPainterToolbox"
```

## 其它杀软

360 / 腾讯电脑管家 / 卡巴斯基等：设置里搜索「信任区 / 排除项 / Exclusions」，
同样添加这两个目录。

## 验证

处理一个 10 秒 1080p 片段，观察任务管理器：

- 未排除：磁盘占用会长时间接近 100%，CPU 里杀软进程明显
- 已排除：磁盘只在写帧瞬间升高，处理总耗时通常下降 10~30%

# 发布流程（Release）

本文记录 v1.3.0 实际是怎么发出去的，照着做就能发下一版。

- **GitHub**：全自动（推 tag → Actions 打包 → 自动建 Release）
- **Gitee**：手动（没有 CI，用 API 传一次；或网页上传）

---

## 0. 先改版本号

版本号只有一个来源：

```python
# pplib/__init__.py
__version__ = "1.3.0"
```

`build/make.ps1` 会读它来命名产物（`ProPainterToolbox-1.3.0-portable.zip`）并写进 zip 文件名。
**先改版本号再打 tag**，否则包名和 tag 对不上。

---

## 1. GitHub：推 tag 自动发布

### 1.1 仓库里要有的东西

`.github/workflows/release.yml`（已提交）：

```yaml
name: build-portable-release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: write          # 建 Release 必须有写权限

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: |
          python -m pip install --upgrade pip
          python -m pip install PySide6 pyinstaller
        shell: pwsh
      - name: 打包（exe + 便携 zip）
        shell: pwsh
        run: |
          $py = (Get-Command python).Source
          ./build/make.ps1 -SkipInstall -Zip -Python $py
      - uses: actions/upload-artifact@v4     # 留存 30 天
        with: { name: portable-zip, path: dist/*.zip }
      - uses: softprops/action-gh-release@v2 # 只有 tag 触发时才发布
        if: startsWith(github.ref, 'refs/tags/')
        with:
          files: dist/*.zip
          generate_release_notes: true
          body: |
            ## ProPainter 视频修复工具箱 ${{ github.ref_name }}
            便携版（约 49 MB）：解压后双击 ProPainterToolbox.exe，
            首次启动会引导在线安装运行时（PyTorch + 模型权重，约 2.5 GB）。
```

> `build/make.ps1` 的 `-Python` 参数是为 CI 加的：runner 上没有 `.venv`，
> 本地开发时省略该参数，脚本会自动用 `.venv\Scripts\python.exe`。

### 1.2 发版命令

```bash
git add -A && git commit -m "chore: bump version to 1.3.1"
git push github main

git tag -a v1.3.1 -m "v1.3.1"
git push github v1.3.1          # ← 这一步触发 Actions
```

### 1.3 它替你做了什么

1. 检出该 tag 的代码
2. `pip install PySide6 pyinstaller`（约 200 MB）
3. `build/make.ps1 -SkipInstall -Zip -Python python`
   → PyInstaller 出 `dist\ProPainterToolbox\`
   → 复制 `pplib/ model/ core/ utils/ RAFT/ tools/*.py` 等运行期脚本
   → `Compress-Archive` 出 `dist\ProPainterToolbox-<版本>-portable.zip`
4. `upload-artifact` 留一份（Actions 页面可下，30 天）
5. `softprops/action-gh-release` 建 Release：tag 名当标题、正文用上面的模板、附件挂 zip

全程 4~6 分钟，不需要任何 token。

### 1.4 验证发布成功

```bash
# 页面存在
curl -I https://github.com/xg-jxk/propainter-toolbox/releases/tag/v1.3.1

# 附件列表（GitHub 的资产是懒加载，主 HTML 里没有链接，要抓这个 fragment）
curl -s https://github.com/xg-jxk/propainter-toolbox/releases/expanded_assets/v1.3.1 \
  | grep -o 'releases/download/v1.3.1/[^"?]*'
```

应看到三个附件：`ProPainterToolbox-<版本>-portable.zip`（我们的产物）+ `v1.3.1.zip` + `v1.3.1.tar.gz`（平台自动生成的源码包）。

### 1.5 手动触发（不发布）

Actions → `build-portable-release` → **Run workflow**。
只会产出 artifact，**不会**建 Release——因为发布那步带 `if: startsWith(github.ref, 'refs/tags/')`。

---

## 2. Gitee：手动传一次

Gitee 没有 GitHub Actions 那种能力，用 OpenAPI 传（在 v1.3.0 上实测可用）。

### 2.1 准备

1. 生成私人令牌：<https://gitee.com/profile/personal_access_tokens>，勾 **projects**
2. 本地先有 zip：`dist\ProPainterToolbox-<版本>-portable.zip`
   （可以和 GitHub 附件**同一份**，这样两边 SHA256 一致）

### 2.2 建 Release

```bash
TOKEN=<你的令牌>
REPO=jiang-xinkai/propainter-toolbox
VER=1.3.0

curl -sS -X POST "https://gitee.com/api/v5/repos/$REPO/releases" \
  -H "User-Agent: Mozilla/5.0" \
  --data-urlencode "access_token=$TOKEN" \
  --data-urlencode "tag_name=v$VER" \
  --data-urlencode "name=v$VER" \
  --data-urlencode "target_commitish=main" \
  --data-urlencode "body@release-notes.md" \
  --data-urlencode "prerelease=false"
```

返回 JSON 里的 `id` 就是 release_id。

> ⚠️ **坑 1：`target_commitish` 是必填**。只给 `tag_name` 会返回
> `400 {"messages":["target_commitish is missing"]}`。

### 2.3 上传附件

先把文件改成正式文件名（**附件名 = 文件名**，不要用临时名）：

```bash
cp dist/ProPainterToolbox-$VER-portable.zip /tmp/ProPainterToolbox-$VER-portable.zip

curl -sS -X POST "https://gitee.com/api/v5/repos/$REPO/releases/<release_id>/attach_files" \
  -H "User-Agent: Mozilla/5.0" \
  -F "access_token=$TOKEN" \
  -F "file=@/tmp/ProPainterToolbox-$VER-portable.zip"
```

> ⚠️ **坑 2：附件名取自文件名**。用 `ci_portable.zip` 这种临时名传上去，
> 页面上就显示 `ci_portable.zip`。发现传错可以删掉重传：

```bash
curl -sS -X DELETE \
  "https://gitee.com/api/v5/repos/$REPO/releases/<release_id>/attach_files/<attach_id>?access_token=$TOKEN"
# 成功返回 204
```

### 2.4 验证

```bash
# 附件清单
curl -sS "https://gitee.com/api/v5/repos/$REPO/releases/<release_id>?access_token=$TOKEN" \
  | python -c "import json,sys;d=json.load(sys.stdin);print([a['name'] for a in d['assets']])"
# 期望：['ProPainterToolbox-1.3.0-portable.zip', 'v1.3.0.zip', 'v1.3.0.tar.gz']

# 下载链路（应 302 → 302 → 200，并给出正确 Content-Length）
curl -I -L "https://gitee.com/$REPO/releases/download/v1.3.0/ProPainterToolbox-1.3.0-portable.zip"
```

### 2.5 或者干脆走网页

<https://gitee.com/jiang-xinkai/propainter-toolbox/releases/new> → 标签 `v1.3.1` →
上传本地 zip → 发布。省事，但每次都要手动点。

---

## 3. 发下一版的完整清单

```text
[ ] 1. 改 pplib/__init__.py 的 __version__
[ ] 2. 更新 README 里出现的版本号 / 截图（如有）
[ ] 3. 本地跑一遍：python -m unittest discover -s tests
[ ] 4. 本地打包自测：build\make.ps1 -SkipInstall -Zip
[ ] 5. commit + push main（GitHub & Gitee）
[ ] 6. git tag -a vX.Y.Z -m "vX.Y.Z" && git push github vX.Y.Z
[ ] 7. 等 Actions 绿 → 检查 Release 附件（expanded_assets fragment）
[ ] 8. 把同一份 zip 传到 Gitee Release（2.3）
[ ] 9. 本地 zip 与两边附件的 SHA256 对一下
```

---

## 4. 常见问题

**Q：Actions 里打包失败在哪看？**
仓库 → Actions → `build-portable-release` → 对应 run → 展开失败的 step。
常见原因：`pip install PySide6` 超时、`make.ps1` 路径问题、`softprops` 没有写权限（检查 workflow 里的 `permissions: contents: write`）。

**Q：为什么便携包只有 49 MB，不是 3 GB？**
包里只有 GUI 外壳 + 脚本；`.venv`（torch）、`weights/`、`tools/realcugan` 都是首次运行时在线装。
另外 `.venv` 里记录绝对路径，预装好再打包换机器也用不了。

**Q：能在 Gitee 上自动化吗？**
Gitee 没有等价的 CI 矩阵（Gitee Go 需要额外开通），目前就走 API/网页手动一次。

**Q：tag 打错了想重发？**
```bash
git tag -d v1.3.0                       # 删本地
git push github :refs/tags/v1.3.0       # 删远端
git push gitee  :refs/tags/v1.3.0
# 然后改版本号/修问题，重新 tag
```
已发布的 Release 需要先在网页删掉，重新触发 Actions 会再建一个。

**Q：Release 附件能替换吗？**
GitHub 不支持覆盖，只能删掉旧附件再传新的（或发个新 tag）。
Gitee 用 `DELETE .../attach_files/{id}` 删掉再传。

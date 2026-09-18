# refs/ —— 外部参考源码

这些目录是**只读参考**，不参与 ChemLayout 的构建与运行。

## Hiro-Smart-Doc

PatSnap 开源的文档解析服务（Apache-2.0），是 `PatSnap/Hiro-Layout` 版面权重与
MOSS-OCR 的官方**使用方**。我们拉它是为了：

1. 拿到 Hiro-Layout ONNX 的**官方预处理/后处理参考实现**与**真实类别顺序**；
2. 分析它与 MBForge 的兼容性；
3. 提取版面识别设计可借鉴的部分。

分析结论见 [`../docs/HIRO-SMART-DOC-ANALYSIS.md`](../docs/HIRO-SMART-DOC-ANALYSIS.md)。

- 上游：<https://github.com/patsnap/Hiro-Smart-Doc>
- 本地版本：`main`，commit `9c1a40f7ec8cfd195701b3b6ad10d72f510817ff`（2026-09-17 拉取）
- 不含权重（`layout_model/` 只有 `.gitkeep`）；ONNX 仍需从 HF 拉：
  `& $PY ../layout/fetch_weights.py --model hiro`

### ⚠️ 本机 `github.com` 直连不可达

实测 `git clone https://github.com/...` 报 `Recv failure: Connection was reset`。
可用镜像（2026-09-17 实测 `ghfast.top` / `ghproxy.net` 均返回 200）：

```powershell
$zip = Join-Path $env:TEMP "hiro-smart-doc.zip"
Invoke-WebRequest -TimeoutSec 180 -OutFile $zip `
  "https://ghfast.top/https://github.com/patsnap/Hiro-Smart-Doc/archive/refs/heads/main.zip"
Expand-Archive -Path $zip -DestinationPath refs -Force
Rename-Item refs\Hiro-Smart-Doc-main Hiro-Smart-Doc
```

（`github.moeyy.xyz` SSL 失败；`gh-proxy.com` 返回 502。GitHub **API** 与 raw 文件
经 WebFetch 通道可达，因此单文件也可以按需取。）

---

同项目组另有 **[Hiro-MOSS-OCR](https://github.com/patsnap/Hiro-MOSS-OCR)**（Hiro-Smart-Doc
调用的 OCR 模型），本仓库不需要它即可跑版面部分，暂未拉取。

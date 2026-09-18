# 运行时与环境

> 约束：**限定 PyTorch 为基础的框架，移除 PaddlePaddle**。
> 本文只描述**当前成立的事实**与**已实施的运行时状态**；未实施的路线统一列在 §6。

---

## 1. 决策

**PyTorch 单栈**。PaddlePaddle 不作为任何已实施模块的运行时。

关键认知：**"限定 PyTorch"不等于要放弃 PaddleOCR 的模型，只需要换掉它的运行时**。
PaddleOCR 3.5 起官方支持 `engine="transformers"`，同一份权重改一行参数即可跑在 PyTorch 上：

```python
TextDetection(model_name="PP-OCRv5_server_det", engine="transformers")
```

官方文档还明确："不同推理引擎之间可能存在依赖冲突，**建议每个环境仅安装一种推理引擎**"——
这既印证了隔离策略，也说明引擎可切换是官方一等设计。

**例外：Hiro-Layout 是 ONNX-only**，不跑在 PyTorch 上，但也不需要 PaddlePaddle——
它走 `onnxruntime-gpu`。因此本项目的实际栈是 **PyTorch + onnxruntime**，
"移除 PaddlePaddle"的约束仍然满足。

---

## 2. 环境

### 2.1 统一环境：MBForge 的 venv（2026-09-18 起）

**唯一环境**：`C:\Users\10954\Desktop\MBForge\.venv`。
ChemLayout 最终要合并回 MBForge，所以不再维护独立环境。

```powershell
$PY = "C:\Users\10954\Desktop\MBForge\.venv\Scripts\python.exe"
```

| 组件 | 版本 | 用于 |
| --- | --- | --- |
| Python | 3.12.13 | — |
| **onnxruntime-gpu** | **1.30.0** | **版面识别**：Hiro-Layout（**CUDA EP 已实测可用**） |
| └ 其依赖的 CUDA 轮子 | `nvidia-cublas 13.8.0.4` / `nvidia-cudnn-cu13 9.26.0.51` / `nvidia-cuda-runtime 13.4.92` | 见 §3 陷阱 6 |
| torch | 2.11.0+cu128 | V3（对照基线）/ MolDet / RapidOCR |
| transformers | 5.17.0 | PP-DocLayoutV3 |
| ultralytics | 8.4.150 | MolDet |
| rapidocr | 3.9.2 | 文本识别 |
| rdkit | 2026.3.6 | 分子处理 |
| PyMuPDF | 1.28.2 | 渲染 / 文本层 |

**变更记录（2026-09-18）**：该环境原先装的是 **`onnxruntime 1.29.0` CPU 版**
（`get_available_providers()` 里连 `CUDAExecutionProvider` 都没有），
这是 Hiro 实测 742 ms/页的直接原因。已按下列步骤换成 GPU 版：

```powershell
uv pip uninstall --python $PY onnxruntime
uv pip install  --python $PY "onnxruntime-gpu[cuda,cudnn]>=1.21"
```

> ⚠️ `onnxruntime` 与 `onnxruntime-gpu` 提供**同一个导入名**，不能共存，
> 必须先把 CPU 版卸掉。`onnxruntime-gpu` 自带 CPU EP，所以 RapidOCR 的 onnx 后端不受影响。

**验证（唯一可信的判据是 `session.get_providers()`）**：

```
onnxruntime-gpu 1.30.0
preload_dlls(): OK
session.get_providers(): ['CUDAExecutionProvider', 'CPUExecutionProvider']   ← CUDA 在前 = 真在 GPU
```

**遗留**：项目自有的 `ChemLayout\.venv`（2.07 GB）因此**不再需要**（当初建它是为了
绕开 MBForge venv 的 CPU onnxruntime，现在那个理由消失了）。**尚未删除** —— 按"不擅自删既有资源"保留，
确认后可直接删。

### 2.2 版本配对风险

`transformers>=5.10.0`（PaddleOCR 3.5 的 transformers 引擎门槛）与 MolDet 的 `torch>=2.0.0`
下限不一致。MBForge venv 当前的组合（torch 2.11.0 + transformers 5.17.0）**已验证可用**，
如需重建环境应锁定这一对。

---

## 3. 环境陷阱（已踩，勿重蹈）

| # | 现象 | 处置 |
| --- | --- | --- |
| 1 | **`huggingface.co` 本机完全不可达**（连接超时/拒绝） | 改用 **ModelScope** 作为默认权重源 |
| 2 | `hf-mirror.com` 可达，但其 **Xet 后端返回 401**，`model.safetensors` 必失败 | 走 HF 时必须 `HF_HUB_DISABLE_XET=1` |
| 3 | **清华 PyPI 镜像在 Windows 上只给 CPU-only torch**（装成 `2.14.0+cpu`，`cuda.is_available()=False`） | CUDA 版走 `--index-url https://download.pytorch.org/whl/cu126`；或直接复用 MBForge venv |
| 4 | ModelScope 上 `PaddlePaddle/PP-DocLayoutV3` 是 `.pdiparams`（**transformers 加载不了**） | 必须用 `PaddlePaddle/PP-DocLayoutV3_safetensors` |
| 5 | **`github.com` 本机直连不可达**（`Recv failure: Connection was reset`） | 走镜像（实测 `ghfast.top` / `ghproxy.net` 可用；见 `refs/README.md`） |
| 6 | **`onnxruntime-gpu` 的 CUDA EP 会"装好了但静默回落 CPU"** | 必须调 `onnxruntime.preload_dlls()`，**且要在建 session 之前**；详见下 |
| 7 | **装了 `onnxruntime-gpu` 后 `import torch` 会崩**（`WinError 127` / `cudnn_cnn64_9.dll`） | **`preload_dlls()` 必须在 `import torch` 之后**；详见下 |

#### 陷阱 6 展开：CUDA EP 静默回落

`onnxruntime-gpu` 的 CUDA EP 依赖 `cublasLt64_*.dll` / `cudnn*.dll`。这些 DLL 随
`nvidia-cublas` / `nvidia-cudnn-cu13` 等轮子安装，但**不在 PATH 上**：

```
[ONNXRuntimeError] : 1 : FAIL : Error loading "...onnxruntime_providers_cuda.dll"
  which depends on "cublasLt64_13.dll" which is missing. (Error 126)
Failed to create CUDAExecutionProvider.
  Require cuDNN 9.* and CUDA 13.*, and the latest MSVC runtime.
```

**最坑的是它会静默回落**：`InferenceSession` 照样建起来，只在 CPU 上跑 —— 而
`ort.get_available_providers()` **仍然列出 `CUDAExecutionProvider`**
（那是"编译进来了"，不是"能加载"）。实测本机缺 DLL 时正是如此，
若不显式检查 `session.get_providers()`，会以为自己在 GPU 上跑（并浪费 6 倍时间）。

**处置**：
1. 建 session 前调 `onnxruntime.preload_dlls()`（`layout/hiro.py::_preload_gpu_dlls`）；
2. 判定是否真在 GPU，**只能看 `session.get_providers()`**，不能看 `get_available_providers()`；
3. `hiro.py` 已在"请求了 CUDA 但实际没拿到"时发 `RuntimeWarning`；
4. providers 列表**显式写 `[CUDA, CPU]`**，不要用默认值——默认值把 TensorRT 排在最前，
   会因缺 `nvinfer_10.dll` 每次会话都刷错误日志。

本机版本对得上（`onnxruntime-gpu 1.30.0` 要 CUDA 13 + cuDNN 9；装进来的是
`nvidia-cuda-runtime 13.4.92` + `nvidia-cudnn-cu13 9.26.0.51`），纯粹是 DLL 路径问题。
注意与 torch 的 **cu128（CUDA 12.8）不是同代**，但两者各自加载自己的 CUDA 轮子，实测不冲突。

#### 陷阱 7 展开：`preload_dlls()` 会抢走 torch 的同名 cuDNN（2026-09-18 实测踩到）

**症状**：装上 `onnxruntime-gpu` 后，**单跑 `import torch` 是好的**，但跑完整管线时崩：

```
OSError: [WinError 127] 找不到指定的程序。
  Error loading "...\torch\lib\cudnn_cnn64_9.dll" or one of its dependencies.
```

**根因**：`preload_dlls()` 把 `nvidia/cudnn/bin`（cuDNN 9 / **CUDA 13**）加进 DLL 搜索路径，
而 **torch 2.11.0+cu128 自带同名 DLL** `torch/lib/cudnn_cnn64_9.dll`（cuDNN 9 / **CUDA 12**）。
Windows 加载器**按名字去重**，于是先注册的一方赢。实测三种顺序：

| 顺序 | 结果 |
| --- | --- |
| `preload_dlls()` → `import torch` | ❌ **torch 崩**（拿到 CUDA 13 那份） |
| `import torch` → `preload_dlls()` | ✅ 正常（各用自己那份），但会警告 CUDA 12 vs 13 不同代 |
| 只 `import onnxruntime`（不 preload）→ `import torch` | ✅ 正常 |

**为什么只在完整管线里暴露**：`detect_overlay.py` 先 `load_hiro()`（触发 `preload_dlls`），
后 `load_moldet()`（才 `import torch`）——正好落在第一种顺序上。

**处置（已实现）**：`layout/hiro.py::_preload_gpu_dlls` 现在**先尽力 `import torch`** 再 preload；
没有 torch 的纯 ONNX 环境不受影响（`try/except` 兜住）。

> ⚠️ **遗留提示**：`torch` 是 cu128（CUDA 12.8），`onnxruntime-gpu 1.30` 是 CUDA 13，
> 每次 `preload_dlls()` 后 torch 都会打印一条不同代的警告。
> 功能上实测无碍（各加载各自那套轮子）。若要彻底消除，
> 可把 ORT 换成 CUDA 12 构建（如 `onnxruntime-gpu 1.22.x` + `nvidia-cudnn-cu12`），
> 使两边 CUDA 同代 —— 但**当前配置已可用，不建议仅为消警告而动**。

---

## 4. 已实施的模块运行时状态

| 阶段 | 模型 | 运行时 | 状态 |
| --- | --- | --- | --- |
| 渲染 | PyMuPDF | C 库 | ✅ |
| **版面识别** | **Hiro-Layout (RT-DETR-X)** | **onnxruntime-gpu 1.30.0（CUDA EP 已实测）** | ✅ **122 ms/页**；权重授权待澄清 |
| **版面识别** | **MolDetv2-YOLO26 (960_doc)** | **ultralytics / PyTorch** | ✅ 已实测 |
| 版面识别 · 合并 | 自有代码（`layout/merge.py`） | 纯 Python | ✅ 已实现 |
| **文本识别** | RapidOCR（PP-OCRv6） | torch / onnxruntime | ⚠️ 已跑通，**引擎未定** |
| 对照基线 | PP-DocLayoutV3 | transformers / PyTorch | ✅ 已实测（`layout/README.md`；非生产路径） |
| 表格识别 | — | — | ❌ 未实施 |
| 公式识别 | — | — | ❌ 未实施 |
| 分子识别 | — | — | ❌ 未实施 |
| 编号关联 | — | — | ❌ 未实施 |
| 反应解析 | — | — | ❌ 未实施 |
| 组装与关联 | — | — | ❌ 未实施 |

---

## 5. OCR 引擎评估结论（**未采用**）

为给文本识别选型，实测了 `rapidocr 3.9.2`（PP-OCRv6），4 页专利、144 DPI、预热后取 3 次中位：

| 引擎 | 设备 | model_type | 加载 | ms/页 |
| --- | --- | --- | ---: | ---: |
| torch | **CUDA** | tiny | 12.95 s | **432.7** |
| torch | **CUDA** | small | 3.29 s | **744.7** |
| torch | **CUDA** | medium | 169.81 s | 1229.6 |
| torch | CPU | small | 3.72 s | 3520.2 |
| onnxruntime | CPU | small | 0.61 s | 1951.4 |
| onnxruntime | CUDA（无效） | small | 0.47 s | 2003.4 |

**四条结论**：

1. **RapidOCR 的 torch 引擎确实不依赖 PaddlePaddle**——本机 `import paddle` 失败仍完整跑通。
   （网上有说法称其 PyTorch 推理只是包装 Paddle 网络结构、绕不开 paddle；对 **3.9.2 不成立**。）
   → 这条绕开了原本的阻塞性闸门："`paddleocr` 能否脱离 `paddlepaddle` 运行"。
2. **`EngineConfig.torch.use_cuda` 默认是 `False`**，不显式打开就在 CPU 上跑，**差 4.7 倍**。
   另外 `params` 取值**必须是 Enum 实例**，传字符串会抛 `TypeError: ... must be Enum Type`。
3. **PP-OCRv6 没有 server 档**，只有 `tiny`/`small`/`medium` 且只有 `multi_*` 变体；
   配 `lang_type='ch' + server` 直接报 `ValueError`。`medium` 首次加载 **169.81 s**，生产上必须预热缓存。
4. **本机 `onnxruntime` 是 CPU 版**（无 `onnxruntime-gpu`），`use_cuda=True` 被**静默忽略**
   （2003 ms ≈ CPU 的 1951 ms）。

**未采用的原因**：文本识别尚未定稿，且实测显示裸跑全页会引入大量污染——
**38.2% 的识别文本行落在结构式/图区域内**（详见 `layout/README.md` §10）。
先用版面识别的区域做遮罩再决定形态，比直接选引擎更重要。

> ⚠️ 注意：`ocr/ocr.py` 里已有一版**可用**的实现（按版面识别的 text 框做行级 OCR，
> 每页只调一次批量 rec）。它与"选哪个引擎"是两个问题——**形状已定，引擎待定**。

---

## 6. 未实施的路线

以下内容**尚未实施**，保留作后续决策参考：

| 项 | 说明 |
| --- | --- |
| **文本识别的三个候选** | ① RapidOCR(torch) —— 零新装、不依赖 paddle、已验证可用，但 PP-OCRv6 无 server 档；② `paddleocr + engine="transformers"` —— 保留 PP-OCRv5 精度，但需验证 `paddleocr` 能否脱离 `paddlepaddle`；③ docTR —— PyTorch 原生，但中文能力显著弱于 PP-OCRv5，对化学专利是硬伤 |
| **表格识别** | 首选 SLANeXt via `engine="transformers"`（**覆盖度未证实**）；兜底 `microsoft/table-transformer-structure-recognition`（MIT，28.8M 参数），但它**只出结构不出带文本的 HTML**，需自写"结构 + 文本 → HTML"的单元格装配层 |
| **公式识别** | 首选 PP-FormulaNet via `engine="transformers"`（**覆盖度未证实**）；兜底 UniMERNet（PyTorch，有 PyPI 包，LICENSE 待确认） |
| **编号关联** | 若文本识别选 RapidOCR，编号关联直接复用同一实例即可，无需独立模型 |
| **阅读顺序** | **Hiro 不输出顺序**（V3 自带逻辑阅读序）。恢复责任在组装层，官方参考实现是 `column_sort` 那套硬编码启发式，**尚未实施** |
| **服务编排** | 只走自有编排器（FastAPI），不走 PaddleX 产线 |
| **进程隔离** | 单栈已消除框架冲突，但**未消除显存与线程争抢**（实测分子检测会使版面检测变慢），仍建议按进程/分卡隔离 |
| **自有 venv 补齐** | 项目 `.venv` 缺 `torch` / `ultralytics`，导致完整管线跑不了（见 §2.1 注） |

### 6.1 因此对 `DESIGN.md` 的改动

- **原 PaddleX 自定义产线 YAML 整节删除**（属 PaddlePaddle 侧）。
- **"A+B 混合"简化为纯 B**。
- **原"PaddleX 扩展成本"风险删除**——不再需要按 PaddleX 接口封装自定义模块，
  跨模块文本传递就是普通 Python 调用。
- §7 授权清单：PaddleOCR 系改为"权重来源，运行时为 transformers"。
- §0.1 记录两条新决策：**版面识别 = Hiro ∪ MolDet**、**全部按扫描件处理**。

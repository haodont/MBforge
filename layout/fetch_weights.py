#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
拉取 M1 的版面检测权重。

两个模型：

  v3    PP-DocLayoutV3        → M1/weights/PP-DocLayoutV3/
        主源 ModelScope  PaddlePaddle/PP-DocLayoutV3_safetensors
        备源 HF 镜像     PaddlePaddle/PP-DocLayoutV3_safetensors

  hiro  Hiro-Layout (PatSnap) → M1/weights/Hiro-Layout/
        仅 HF 镜像      PatSnap/Hiro-Layout     （ModelScope 上没有，实测 404）

⚠️ 本机 `huggingface.co` 不可达；`hf-mirror.com` 可达，但其 Xet 后端返回 401，
   `model.safetensors` / 大 ONNX 会下载失败，**必须** `HF_HUB_DISABLE_XET=1`。

⚠️ ModelScope 上有两个同名 PP-DocLayoutV3 仓库，别拉错：
     PaddlePaddle/PP-DocLayoutV3               → inference.pdiparams（Paddle 格式，transformers 加载不了）
     PaddlePaddle/PP-DocLayoutV3_safetensors   → model.safetensors（transformers 用这个）★

用法：
    python fetch_weights.py                  # v3（默认），走 ModelScope
    python fetch_weights.py --model hiro     # Hiro-Layout，走 HF 镜像
    python fetch_weights.py --model v3 --hf  # v3 改走 HF 镜像
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

HF_ENDPOINT = "https://hf-mirror.com"

# ---------------------------------------------------------------------------- v3
MS_REPO_V3 = "PaddlePaddle/PP-DocLayoutV3_safetensors"
HF_REPO_V3 = "PaddlePaddle/PP-DocLayoutV3_safetensors"
DEST_V3 = HERE / "weights" / "v3"
FILES_V3 = [
    ("model.safetensors", 133_270_468),
    ("config.json", 2_460),
    ("preprocessor_config.json", 575),
    ("inference.yml", 1_482),
]

# -------------------------------------------------------------------------- hiro
HF_REPO_HIRO = "PatSnap/Hiro-Layout"
DEST_HIRO = HERE / "weights" / "hiro"
FILES_HIRO = [
    ("layout_model/RT-DETR_25.onnx", 262_468_484),
    ("config.json", 1_411),
    ("labels.json", 2_218),
    ("requirements.txt", 49),
    ("LICENSE", 10_233),
    ("README_zh.md", 9_571),
]

MODELS = {
    "v3": dict(ms_repo=MS_REPO_V3, hf_repo=HF_REPO_V3, dest=DEST_V3, files=FILES_V3),
    "hiro": dict(ms_repo=None, hf_repo=HF_REPO_HIRO, dest=DEST_HIRO, files=FILES_HIRO),
}


def ms_url(repo: str, filename: str) -> str:
    return (f"https://www.modelscope.cn/api/v1/models/{repo}"
            f"/repo?Revision=master&FilePath={filename}")


def download_ms(repo: str, dest: Path, files) -> int:
    print(f"[fetch] source = ModelScope")
    print(f"[fetch] repo   = {repo}")
    print(f"[fetch] dest   = {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    for name, expect in files:
        out = dest / name
        if out.exists() and expect and abs(out.stat().st_size - expect) < 1024:
            print(f"  [skip] {name} 已存在 ({out.stat().st_size:,} B)")
            continue
        url = ms_url(repo, name)
        print(f"  [get ] {name}  ({expect / 1024 / 1024:.2f} MB)" if expect
              else f"  [get ] {name}")
        tmp = out.with_suffix(out.suffix + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
                total, done, last = expect or 0, 0, -1
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    pct = int(done * 100 / total) if total else 0
                    if pct != last and pct % 10 == 0:
                        print(f"         {pct:>3}%  {done / 1024 / 1024:.1f} MB")
                        last = pct
            tmp.replace(out)
            print(f"         done  {out.stat().st_size:,} B")
        except Exception as e:
            tmp.unlink(missing_ok=True)
            print(f"  [FAIL] {name}: {e}")
            return 1
    return 0


def download_hf(repo: str, dest: Path, files, endpoint: str = HF_ENDPOINT) -> int:
    print(f"[fetch] source = HuggingFace mirror ({endpoint})")
    print(f"[fetch] repo   = {repo}")
    print(f"[fetch] dest   = {dest}")
    os.environ["HF_ENDPOINT"] = endpoint
    os.environ["HF_HUB_DISABLE_XET"] = "1"   # Xet CAS 在镜像上返回 401，必须禁用
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return _msg_missing("huggingface_hub")
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo,
        local_dir=str(dest),
        allow_patterns=[f for f, _ in files],
        endpoint=endpoint,
    )
    return 0


def _msg_missing(pkg):
    print(f"缺少 {pkg}。若用 MBForge 的 venv 复用环境，请显式指定解释器。")
    return 1


def verify(dest: Path, files) -> int:
    print("\n[verify] 文件检查：")
    ok = True
    total = 0.0
    for name, expect in files:
        p = dest / name
        if p.exists():
            mb = p.stat().st_size / 1024 / 1024
            total += mb
            flag = "OK  " if (not expect or abs(p.stat().st_size - expect) < 1024) else "SIZE?"
            print(f"  {flag} {name:<28} {mb:>9.2f} MB")
        else:
            ok = False
            print(f"  MISS {name}")
    print(f"  合计 {total:.2f} MB")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="v3", choices=sorted(MODELS),
                    help="v3 = PP-DocLayoutV3（默认，ModelScope）；hiro = Hiro-Layout（HF 镜像）")
    ap.add_argument("--hf", action="store_true",
                    help="v3 改走 HF 镜像（hiro 本来就只有 HF 源）")
    ap.add_argument("--dest", default="")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    cfg = MODELS[args.model]
    dest = Path(args.dest) if args.dest else cfg["dest"]

    if not args.verify_only:
        use_ms = cfg["ms_repo"] and not args.hf
        if use_ms:
            rc = download_ms(cfg["ms_repo"], dest, cfg["files"])
        else:
            rc = download_hf(cfg["hf_repo"], dest, cfg["files"])
        if rc != 0:
            return rc
    return verify(dest, cfg["files"])


if __name__ == "__main__":
    sys.exit(main())

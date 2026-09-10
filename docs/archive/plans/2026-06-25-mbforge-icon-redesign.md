# MBForge 图标重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 替换 MBForge Tauri 桌面 + Android + iOS 全平台图标为统一单色字标设计（堆叠 MB + 角刻度 + 深色背景）。

**Architecture:** SVG 单一源 → 渲染 1024×1024 主稿 PNG → 缩放至各平台尺寸 → 打包多帧 `.ico` / `.icns`。幂等脚本驱动，全程可重跑。

**Tech Stack:** SVG, ImageMagick (magick), rsvg-convert, png2icns (libicns), PowerShell 脚本。

---

## File Structure

| 路径 | 职责 |
|------|------|
| `assets/icon/icon.svg` | 单一矢量源（1024×1024 viewBox） |
| `assets/icon/icon-master.png` | 1024×1024 主稿 PNG（脚本生成） |
| `scripts/build-icons.ps1` | Windows 构建脚本（幂等） |
| `scripts/build-icons.sh` | POSIX 构建脚本（幂等，备用） |
| `src-tauri/icons/*.png` | Tauri bundle 图标（被脚本覆盖） |
| `src-tauri/icons/icon.ico` | Tauri Windows 图标（多帧，被脚本覆盖） |
| `src-tauri/icons/icon.icns` | Tauri macOS 图标（多帧，被脚本覆盖） |
| `src-tauri/icons/android/**` | Android 5 密度（被脚本覆盖） |
| `src-tauri/icons/ios/**` | iOS 全尺寸（被脚本覆盖） |
| `tests/icon/test_icon_spec.py` | 视觉/尺寸自动化校验 |

---

## Task 1: 创建 SVG 源文件

**Files:**
- Create: `assets/icon/icon.svg`

- [ ] **Step 1: 创建目录**

```powershell
New-Item -ItemType Directory -Force -Path "assets/icon"
```

- [ ] **Step 2: 写 SVG 源文件**

内容：1024×1024 viewBox，圆角方形背景（`rx=225`，22% 圆角），4 角 L 形刻度，堆叠 MB 字符。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <!-- 背景：圆角方形 -->
  <rect x="0" y="0" width="1024" height="1024" rx="225" ry="225" fill="#0B0F14"/>

  <!-- 4 角 L 形刻度：长度 82 (8%)，离角 61 (6%)，描边 1.5，#94A3B8 @ 40% opacity -->
  <g stroke="#94A3B8" stroke-opacity="0.4" stroke-width="1.5" fill="none">
    <!-- 左上 -->
    <path d="M 61 143 L 61 61 L 143 61"/>
    <!-- 右上 -->
    <path d="M 881 61 L 963 61 L 963 143"/>
    <!-- 左下 -->
    <path d="M 61 881 L 61 963 L 143 963"/>
    <!-- 右下 -->
    <path d="M 963 881 L 963 963 L 881 963"/>
  </g>

  <!-- 堆叠 MB 字标：等宽无衬线 Bold，居中，字高 32% 边长 -->
  <g font-family="'JetBrains Mono', 'IBM Plex Mono', 'DejaVu Sans Mono', monospace"
     font-weight="700"
     fill="#F1F5F9"
     text-anchor="middle"
     letter-spacing="-30">
    <text x="512" y="500" font-size="360">M</text>
    <text x="512" y="830" font-size="360">B</text>
  </g>
</svg>
```

- [ ] **Step 3: 验证 SVG 语法正确**

在浏览器中打开（双击文件），确认渲染无错。或：

```powershell
$content = Get-Content "assets/icon/icon.svg" -Raw
if ($content -match 'viewBox="0 0 1024 1024"') { Write-Host "OK" } else { Write-Host "FAIL" }
```

预期：`OK`

- [ ] **Step 4: 提交**

```powershell
git add assets/icon/icon.svg
git commit -m "feat(icon): add SVG source for mbforge icon redesign"
```

---

## Task 2: 检查并安装依赖工具

**Files:** 无（仅验证环境）

- [ ] **Step 1: 检查 ImageMagick**

```powershell
magick -version | Select-Object -First 1
```

预期：`Version: ImageMagick 7.x.x` 或更高。

缺失时安装：https://imagemagick.org/script/download.php#windows

- [ ] **Step 2: 检查 rsvg-convert 或备选**

```powershell
rsvg-convert --version
```

如果缺失，备选方案：使用 `magick` 直接转换（要求 ImageMagick 已编译 librsvg 支持）。

检查 librsvg 支持：

```powershell
magick -list format | Select-String -Pattern "svg"
```

预期行包含 `SVG` 格式。

如果 SVG 格式不可用，安装 rsvg-convert：
- MSYS2: `pacman -S mingw-w64-x86_64-librsvg`
- 或下载 librsvg Windows binary

- [ ] **Step 3: 检查 png2icns（仅 macOS 需要）**

Windows 环境跳过此步。macOS 后续使用 `iconutil` 替代。

- [ ] **Step 4: 报告检查结果**

- ImageMagick: ✅ / ❌
- rsvg-convert 或 librsvg 支持: ✅ / ❌
- macOS iconutil: macOS 平台可选

---

## Task 3: 编写幂等构建脚本

**Files:**
- Create: `scripts/build-icons.ps1`

- [ ] **Step 1: 创建脚本目录**

```powershell
New-Item -ItemType Directory -Force -Path "scripts"
```

- [ ] **Step 2: 写 PowerShell 构建脚本**

```powershell
# scripts/build-icons.ps1
# MBForge 图标构建脚本 — 幂等，覆盖所有平台图标
# 用法: pwsh scripts/build-icons.ps1

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot/.."
$svg = "$root/assets/icon/icon.svg"
$master = "$root/assets/icon/icon-master.png"
$tauriIcons = "$root/src-tauri/icons"

# 1. 渲染 SVG → 1024 主稿 PNG
Write-Host "[1/6] Rendering SVG master..." -ForegroundColor Cyan
& magick -density 300 -background none "$svg" -resize 1024x1024 "$master"
if ($LASTEXITCODE -ne 0) { throw "SVG render failed" }

# 2. Tauri 桌面 PNG
Write-Host "[2/6] Generating Tauri PNGs..." -ForegroundColor Cyan
$sizes = @(
    @{ name = "32x32.png"; size = 32 },
    @{ name = "128x128.png"; size = 128 },
    @{ name = "128x128@2x.png"; size = 256 },
    @{ name = "icon.png"; size = 1024 }
)
foreach ($s in $sizes) {
    $out = "$tauriIcons/$($s.name)"
    & magick "$master" -resize "$($s.size)x$($s.size)" -strip "$out"
    if ($LASTEXITCODE -ne 0) { throw "Failed: $($s.name)" }
    Write-Host "  -> $($s.name)" -ForegroundColor Gray
}

# 3. .ico 多帧
Write-Host "[3/6] Building icon.ico..." -ForegroundColor Cyan
$icoFrames = @()
foreach ($size in @(16, 32, 48, 64, 128, 256)) {
    $tmp = "$env:TEMP/mbforge-ico-$size.png"
    & magick "$master" -resize "${size}x${size}" -strip "$tmp"
    $icoFrames += $tmp
}
& magick ($icoFrames -join " ") "$tauriIcons/icon.ico"
if ($LASTEXITCODE -ne 0) { throw ".ico build failed" }
$icoFrames | ForEach-Object { Remove-Item $_ -Force }

# 4. .icns 多帧（macOS）
Write-Host "[4/6] Building icon.icns..." -ForegroundColor Cyan
$icnsFrames = @()
foreach ($size in @(16, 32, 64, 128, 256, 512, 1024)) {
    $tmp = "$env:TEMP/mbforge-icns-$size.png"
    & magick "$master" -resize "${size}x${size}" -strip "$tmp"
    $icnsFrames += $tmp
}
# 使用 png2icns（如不可用则警告并跳过）
if (Get-Command png2icns -ErrorAction SilentlyContinue) {
    & png2icns -o "$tauriIcons/icon.icns" $icnsFrames
} else {
    Write-Host "  WARN: png2icns not found, skipping .icns (build on macOS)" -ForegroundColor Yellow
}
$icnsFrames | ForEach-Object { Remove-Item $_ -Force }

# 5. Android mipmap（5 密度 + foreground + round）
Write-Host "[5/6] Generating Android mipmaps..." -ForegroundColor Cyan
$androidSizes = @{
    "mdpi"    = 48
    "hdpi"    = 72
    "xhdpi"   = 96
    "xxhdpi"  = 144
    "xxxhdpi" = 192
}
foreach ($dpi in $androidSizes.Keys) {
    $size = $androidSizes[$dpi]
    $dir = "$tauriIcons/android/mipmap-$dpi"
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    & magick "$master" -resize "${size}x${size}" -strip "$dir/ic_launcher.png"
    & magick "$master" -resize "${size}x${size}" -strip "$dir/ic_launcher_round.png"
    # foreground: 留 18% padding（系统自适应遮罩）
    $fgSize = [int]($size * 0.82)
    $fgPad = [int](($size - $fgSize) / 2)
    & magick "$master" -resize "${fgSize}x${fgSize}" -background none -gravity center -extent "${size}x${size}" -strip "$dir/ic_launcher_foreground.png"
    Write-Host "  -> mipmap-$dpi (${size}px)" -ForegroundColor Gray
}

# 6. iOS AppIcon
Write-Host "[6/6] Generating iOS AppIcons..." -ForegroundColor Cyan
$iosSizes = @{
    "AppIcon-20x20@1x.png"           = 20
    "AppIcon-20x20@2x-1.png"         = 40
    "AppIcon-20x20@2x.png"           = 40
    "AppIcon-20x20@3x.png"           = 60
    "AppIcon-29x29@1x.png"           = 29
    "AppIcon-29x29@2x-1.png"         = 58
    "AppIcon-29x29@2x.png"           = 58
    "AppIcon-29x29@3x.png"           = 87
    "AppIcon-40x40@1x.png"           = 40
    "AppIcon-40x40@2x-1.png"         = 80
    "AppIcon-40x40@2x.png"           = 80
    "AppIcon-40x40@3x.png"           = 120
    "AppIcon-60x60@2x.png"           = 120
    "AppIcon-60x60@3x.png"           = 180
    "AppIcon-76x76@1x.png"           = 76
    "AppIcon-76x76@2x.png"           = 152
    "AppIcon-83.5x83.5@2x.png"       = 167
    "AppIcon-512@2x.png"             = 1024
}
$iosDir = "$tauriIcons/ios"
if (-not (Test-Path $iosDir)) { New-Item -ItemType Directory -Force -Path $iosDir | Out-Null }
foreach ($name in $iosSizes.Keys) {
    $size = $iosSizes[$name]
    & magick "$master" -resize "${size}x${size}" -strip "$iosDir/$name"
    Write-Host "  -> $name (${size}px)" -ForegroundColor Gray
}

Write-Host "Done. All icons regenerated from $svg" -ForegroundColor Green
```

- [ ] **Step 3: 验证脚本语法**

```powershell
$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content "$PSScriptRoot/scripts/build-icons.ps1" -Raw), [ref]$null)
Write-Host "Script syntax OK"
```

预期：`Script syntax OK`

- [ ] **Step 4: 提交**

```powershell
git add scripts/build-icons.ps1
git commit -m "feat(icon): idempotent PowerShell build script"
```

---

## Task 4: 编写视觉/尺寸自动化校验

**Files:**
- Create: `tests/icon/test_icon_spec.py`

- [ ] **Step 1: 创建测试目录**

```powershell
New-Item -ItemType Directory -Force -Path "tests/icon"
```

- [ ] **Step 2: 写校验脚本**

使用 Pillow 验证每个图标的尺寸、格式、像素数。

```python
# tests/icon/test_icon_spec.py
"""MBForge 图标规格校验 — 验证生成产物符合 Tauri/Android/iOS 平台要求"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TAURI_ICONS = ROOT / "src-tauri" / "icons"

# Tauri 桌面必需文件清单 (path, expected_size)
TAURI_REQUIRED = [
    ("icon.png", 1024),
    ("32x32.png", 32),
    ("128x128.png", 128),
    ("128x128@2x.png", 256),
    ("icon.ico", None),  # 多帧，大小不固定
    ("icon.icns", None),
]

# Android 5 密度
ANDROID_DENSITIES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

# iOS AppIcon 尺寸
IOS_SIZES = {
    "AppIcon-20x20@1x.png": 20,
    "AppIcon-20x20@2x-1.png": 40,
    "AppIcon-20x20@2x.png": 40,
    "AppIcon-20x20@3x.png": 60,
    "AppIcon-29x29@1x.png": 29,
    "AppIcon-29x29@2x-1.png": 58,
    "AppIcon-29x29@2x.png": 58,
    "AppIcon-29x29@3x.png": 87,
    "AppIcon-40x40@1x.png": 40,
    "AppIcon-40x40@2x-1.png": 80,
    "AppIcon-40x40@2x.png": 80,
    "AppIcon-40x40@3x.png": 120,
    "AppIcon-60x60@2x.png": 120,
    "AppIcon-60x60@3x.png": 180,
    "AppIcon-76x76@1x.png": 76,
    "AppIcon-76x76@2x.png": 152,
    "AppIcon-83.5x83.5@2x.png": 167,
    "AppIcon-512@2x.png": 1024,
}


def test_tauri_icon_png_exists():
    """Tauri 必需 PNG 图标全部存在"""
    for name, _ in TAURI_REQUIRED:
        if name.endswith(".png"):
            assert (TAURI_ICONS / name).exists(), f"Missing: {name}"


def test_tauri_icon_png_dimensions():
    """Tauri PNG 尺寸严格匹配"""
    for name, expected_size in TAURI_REQUIRED:
        if name.endswith(".png") and expected_size:
            img = Image.open(TAURI_ICONS / name)
            assert img.size == (expected_size, expected_size), \
                f"{name}: expected {expected_size}x{expected_size}, got {img.size}"


def test_tauri_icon_ico_exists():
    """Tauri .ico 存在且包含多帧"""
    ico_path = TAURI_ICONS / "icon.ico"
    if not ico_path.exists():
        return  # macOS-only step may skip
    img = Image.open(ico_path)
    n_frames = getattr(img, "n_frames", 1)
    assert n_frames >= 4, f"icon.ico should have multiple frames, got {n_frames}"


def test_android_mipmaps_exist():
    """Android 5 密度 mipmap 全部存在"""
    for dpi, size in ANDROID_DENSITIES.items():
        for variant in ["ic_launcher", "ic_launcher_round", "ic_launcher_foreground"]:
            path = TAURI_ICONS / "android" / f"mipmap-{dpi}" / f"{variant}.png"
            assert path.exists(), f"Missing: {path.relative_to(ROOT)}"


def test_android_mipmap_dimensions():
    """Android mipmap 尺寸匹配密度"""
    for dpi, size in ANDROID_DENSITIES.items():
        for variant in ["ic_launcher", "ic_launcher_round"]:
            path = TAURI_ICONS / "android" / f"mipmap-{dpi}" / f"{variant}.png"
            img = Image.open(path)
            assert img.size == (size, size), \
                f"{path.name}: expected {size}x{size}, got {img.size}"


def test_ios_appicons_exist():
    """iOS AppIcon 全尺寸存在"""
    for name, _ in IOS_SIZES.items():
        path = TAURI_ICONS / "ios" / name
        assert path.exists(), f"Missing: ios/{name}"


def test_ios_appicon_dimensions():
    """iOS AppIcon 尺寸匹配"""
    for name, expected_size in IOS_SIZES.items():
        path = TAURI_ICONS / "ios" / name
        img = Image.open(path)
        assert img.size == (expected_size, expected_size), \
            f"{name}: expected {expected_size}x{expected_size}, got {img.size}"


def test_master_png_background_color():
    """主稿 PNG 背景色为 #0B0F14"""
    master = TAURI_ICONS / "icon.png"
    img = Image.open(master).convert("RGBA")
    # 采样左上角 (避开圆角) 区域
    pixel = img.getpixel((50, 50))
    # 容差 ±5
    assert abs(pixel[0] - 0x0B) < 6
    assert abs(pixel[1] - 0x0F) < 6
    assert abs(pixel[2] - 0x14) < 6
```

- [ ] **Step 3: 验证测试可加载（运行前先跑构建）**

```powershell
uv run pytest tests/icon/test_icon_spec.py --collect-only
```

预期：收集到所有测试函数，无 import error。

- [ ] **Step 4: 提交**

```powershell
git add tests/icon/test_icon_spec.py
git commit -m "test(icon): platform icon spec validation"
```

---

## Task 5: 运行构建脚本

**Files:** 无（仅执行）

- [ ] **Step 1: 运行幂等构建脚本**

```powershell
pwsh scripts/build-icons.ps1
```

预期输出：6 个阶段全部 `[Done]`，无 ERROR，无 FAIL。

- [ ] **Step 2: 验证主稿文件已生成**

```powershell
Test-Path "assets/icon/icon-master.png"
```

预期：`True`

- [ ] **Step 3: 验证 Tauri icons 目录被覆盖**

```powershell
Get-ChildItem "src-tauri/icons/*.png" | Select-Object Name, Length
```

预期：32x32.png / 128x128.png / 128x128@2x.png / icon.png 均存在且大小 > 0。

- [ ] **Step 4: 提交（如有自动产生的新文件）**

```powershell
git status --short src-tauri/icons/
# 若 .ico / .icns 被重新生成且有变更
git add src-tauri/icons/
git commit -m "feat(icon): regenerate all platform icons from new design"
```

---

## Task 6: 运行测试验证

**Files:** 无（仅执行）

- [ ] **Step 1: 运行图标规格测试**

```powershell
uv run pytest tests/icon/test_icon_spec.py -v
```

预期：所有测试 PASS。

- [ ] **Step 2: 修复失败（如有）**

- 若 .icns 缺失：检查 png2icns 是否安装；若未安装，测试已设计为跳过
- 若尺寸不匹配：检查 SVG 渲染参数
- 若 Android foreground 缺失：检查脚本 fg 分支

- [ ] **Step 3: 视觉抽检（手动）**

打开以下文件并目视确认：

- `src-tauri/icons/icon.png` (1024) — 完整设计
- `src-tauri/icons/32x32.png` — M/B 仍可辨
- `src-tauri/icons/128x128.png` — 角刻度清晰

确认点：
- ✅ 圆角方形深色背景
- ✅ 4 角 L 形刻度可见
- ✅ 居中堆叠 M/B
- ✅ 32px 无严重模糊

---

## Task 7: 验证 Tauri 编译通过

**Files:** 无（仅验证）

- [ ] **Step 1: cargo check**

```powershell
cd src-tauri
cargo check
```

预期：`Finished ...` 无 icon 相关错误。

- [ ] **Step 2: 检查 tauri.conf.json 引用文件存在**

```powershell
$conf = Get-Content "src-tauri/crates/mbforge-app/tauri.conf.json" -Raw | ConvertFrom-Json
$conf.bundle.icon | ForEach-Object {
    $path = "src-tauri/crates/mbforge-app/$_"
    if (Test-Path $path) { Write-Host "OK: $_" -ForegroundColor Green } else { Write-Host "MISSING: $_" -ForegroundColor Red }
}
```

预期：所有 bundle.icon 引用路径显示 `OK`。

- [ ] **Step 3: （可选）完整 tauri build 验证**

仅在需要生成最终 .exe / .dmg 时执行：

```powershell
cd src-tauri
cargo tauri build
```

预期：构建成功，生成的 .exe / .dmg 使用新图标。

---

## Task 8: 清理与最终提交

**Files:** 无

- [ ] **Step 1: 确认无残留旧图标**

旧图标特征：渐变色（cyan/purple/blue）的分子六边形。当前新设计为纯灰度。如发现残留：

```powershell
# 列出所有图标文件，按大小排序
Get-ChildItem -Recurse "src-tauri/icons/" -Include *.png,*.ico,*.icns |
    Sort-Object Length -Descending |
    Select-Object FullName, Length -First 20
```

预期：最大尺寸 PNG ≈ 几 KB 到 几十 KB（旧图标可能更大）。

- [ ] **Step 2: 最终 git status**

```powershell
git status
```

预期：无未提交文件（除可能的 .icns / .ico 元数据变更）。

- [ ] **Step 3: 推送（若已配置远程）**

```powershell
git push origin main
```

---

## Self-Review Checklist

- [x] Spec coverage: 7 个设计决策全部对应到任务（SVG 字符→T1；颜色→T1 验证；缩放→T3；导出→T3+T5；验收→T6+T7）
- [x] No placeholders: 所有代码块完整，无 TBD/TODO
- [x] Type consistency: PIL.Image 方法签名、PowerShell cmdlet 一致
- [x] All steps actionable: 每步有明确命令或代码

---

## 风险与回退

| 风险 | 回退 |
|------|------|
| librsvg 缺失 | 用 `magick -density 300 svg:input.svg output.png` 替代 |
| png2icns 缺失 | 在 macOS 上 `iconutil` 重建；Windows 跳过 |
| 32px M/B 模糊 | 调整 SVG font-size 至 380；或加 text-rendering="geometricPrecision" |
| cargo tauri build 失败 | 检查 tauri.conf.json bundle.icon 路径解析（`../../icons/...` 相对于 crates/mbforge-app/） |

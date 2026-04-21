from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import rawpy
except Exception:
    rawpy = None

VALID_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".nef", ".dng", ".cr2"}
RAW_EXT = {".nef", ".dng", ".cr2"}


def load_rgb(path: Path) -> Optional[np.ndarray]:
    ext = path.suffix.lower()
    if ext in RAW_EXT:
        if rawpy is None:
            return None
        try:
            with rawpy.imread(str(path)) as raw:
                return raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
        except Exception:
            return None

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def ensure_clean_dirs(out_root: Path) -> None:
    for split in ("train", "val"):
        for cls in ("blurry", "sharp"):
            d = out_root / split / cls
            d.mkdir(parents=True, exist_ok=True)
            for old in d.glob("*.jpg"):
                old.unlink(missing_ok=True)


def classify_file(path: Path) -> str:
    name = path.stem.lower()
    if "sharp" in name:
        return "sharp"

    blurry_keywords = [
        "blur",
        "motion",
        "noise",
        "gausin",
        "gaussian",
        "dept",
        "depth",
        "field",
        "bokeh",
        "shake",
    ]
    if any(k in name for k in blurry_keywords):
        return "blurry"

    return "blurry"


def random_crop(img: np.ndarray, min_size: int = 224, max_size: int = 768) -> np.ndarray:
    h, w = img.shape[:2]
    side = min(h, w)
    if side <= min_size:
        return img
    crop_size = random.randint(min_size, min(max_size, side))
    y0 = random.randint(0, h - crop_size)
    x0 = random.randint(0, w - crop_size)
    return img[y0 : y0 + crop_size, x0 : x0 + crop_size]


def motion_blur(img: np.ndarray, ksize: int, angle: float) -> np.ndarray:
    ksize = max(3, int(ksize) | 1)
    kernel = np.zeros((ksize, ksize), dtype=np.float32)
    kernel[ksize // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((ksize / 2 - 0.5, ksize / 2 - 0.5), angle, 1.0)
    kernel = cv2.warpAffine(kernel, rot, (ksize, ksize))
    s = kernel.sum()
    if s <= 0:
        kernel[ksize // 2, :] = 1.0
        s = kernel.sum()
    kernel /= s
    return cv2.filter2D(img, -1, kernel)


def blur_augment(rgb: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    if random.random() < 0.85:
        sigma = random.uniform(1.0, 4.5)
        k = int(max(3, round(sigma * 4) | 1))
        out = cv2.GaussianBlur(out, (k, k), sigmaX=sigma, sigmaY=sigma)
    if random.random() < 0.7:
        out = motion_blur(out, ksize=random.randint(7, 27), angle=random.uniform(0.0, 180.0))
    if random.random() < 0.55:
        noise = np.random.normal(0, random.uniform(3, 14), out.shape).astype(np.float32)
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return out


def sharp_augment(rgb: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    if random.random() < 0.45:
        alpha = random.uniform(0.95, 1.08)
        beta = random.uniform(-6, 6)
        out = np.clip(out.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)
    if random.random() < 0.3:
        kernel = np.array([[0, -1, 0], [-1, 5.2, -1], [0, -1, 0]], dtype=np.float32)
        out = np.clip(cv2.filter2D(out, -1, kernel), 0, 255).astype(np.uint8)
    return out


def save_patch(img: np.ndarray, dest: Path) -> None:
    resized = cv2.resize(img, (224, 224), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(resized, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(dest), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])


def split_dest(base: Path, cls: str, idx: int, val_every: int) -> Path:
    split = "val" if (idx % val_every == 0) else "train"
    return base / split / cls


def build_dataset(args) -> Dict[str, int]:
    src = Path(args.source_dir).resolve()
    out = Path(args.output_dir).resolve()
    if not src.exists():
        raise RuntimeError(f"source_dir not found: {src}")

    ensure_clean_dirs(out)

    files = [p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in VALID_EXT]
    if not files:
        raise RuntimeError(f"No supported images found in {src}")

    random.shuffle(files)
    counters = {"blurry": 0, "sharp": 0, "skipped": 0}

    for p in files:
        cls = classify_file(p)
        rgb = load_rgb(p)
        if rgb is None:
            counters["skipped"] += 1
            continue

        repeats = args.blurry_per_image if cls == "blurry" else args.sharp_per_image
        for _ in range(repeats):
            patch = random_crop(rgb, min_size=args.min_crop, max_size=args.max_crop)
            patch = blur_augment(patch) if cls == "blurry" else sharp_augment(patch)
            idx = counters[cls]
            dest_dir = split_dest(out, cls, idx, args.val_every)
            name = f"{p.stem.lower().replace(' ', '_')}_{idx:06d}.jpg"
            save_patch(patch, dest_dir / name)
            counters[cls] += 1

    return counters


def parse_args():
    parser = argparse.ArgumentParser(description="Build blur/sharp dataset from user category photos")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "dataset"),
    )
    parser.add_argument("--blurry-per-image", type=int, default=700)
    parser.add_argument("--sharp-per-image", type=int, default=1200)
    parser.add_argument("--min-crop", type=int, default=224)
    parser.add_argument("--max-crop", type=int, default=1024)
    parser.add_argument("--val-every", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    stats = build_dataset(args)
    print("Dataset generated")
    print(stats)

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import rawpy

VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".nef", ".dng", ".cr2"}
RAW_EXT = {".nef", ".dng", ".cr2"}


def _detect_largest_face(gray: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """Return the largest detected face bbox (x, y, w, h), or None."""
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        return None

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(40, 40),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )

    if len(faces) == 0:
        return None

    return max(faces, key=lambda f: int(f[2]) * int(f[3]))


def _crop_inner_face(gray: np.ndarray, face: tuple[int, int, int, int]) -> np.ndarray:
    """Crop to central face region to reduce hair/background bias in lighting checks."""
    x, y, w, h = face
    h_img, w_img = gray.shape

    x1 = max(0, x + int(0.10 * w))
    x2 = min(w_img, x + int(0.90 * w))
    y1 = max(0, y + int(0.12 * h))
    y2 = min(h_img, y + int(0.92 * h))

    if x2 <= x1 or y2 <= y1:
        return gray[y : y + h, x : x + w]
    return gray[y1:y2, x1:x2]


def _trimmed_mean(arr: np.ndarray, low_pct: float = 5.0, high_pct: float = 95.0) -> float:
    flat = arr.astype(np.float32).reshape(-1)
    if flat.size == 0:
        return 0.0
    lo = np.percentile(flat, low_pct)
    hi = np.percentile(flat, high_pct)
    clipped = flat[(flat >= lo) & (flat <= hi)]
    if clipped.size == 0:
        return float(np.mean(flat))
    return float(np.mean(clipped))


def _collect_images(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VALID_EXT:
            files.append(path)
    files.sort(key=lambda p: p.as_posix().lower())
    return files


def _load_rgb(path: Path) -> Optional[np.ndarray]:
    ext = path.suffix.lower()
    if ext in RAW_EXT:
        try:
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            return rgb
        except Exception:
            return None

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _analyze_lighting(
    gray: np.ndarray,
    min_brightness: float,
    max_brightness: float,
    min_contrast: float,
    balance_threshold: float,
    max_balance_ratio: float,
) -> Dict[str, Any]:
    """
    Analyze lighting quality using simple, tunable thresholds.
    
    Args:
        gray: Grayscale image
        min_brightness: Images darker than this are flagged (e.g., 50-60)
        max_brightness: Images brighter than this are flagged as washed-out (e.g., 180-200)
        min_contrast: Std dev below this indicates low contrast/flat lighting (e.g., 30-40)
        balance_threshold: Left-right brightness diff above this is unbalanced (e.g., 35-50)
    
    Returns:
        Dict with metrics and quality flags
    """
    if gray.size < 100:
        return {"brightness": 0, "contrast": 0, "balance_diff": 0, "has_bad_lighting": True, "reason": "image_too_small"}

    face = _detect_largest_face(gray)
    if face is not None:
        roi = _crop_inner_face(gray, face)
        region_used = "face"
    else:
        # Fallback keeps behavior available for non-face images.
        roi = gray
        region_used = "full_image"

    brightness = float(np.mean(roi))
    contrast = float(np.std(roi))

    h, w = roi.shape
    cx1 = int(0.20 * w)
    cx2 = int(0.80 * w)
    cy1 = int(0.20 * h)
    cy2 = int(0.90 * h)
    core = roi[cy1:cy2, cx1:cx2] if cx2 > cx1 and cy2 > cy1 else roi

    h_core, w_core = core.shape
    left_half = core[:, : w_core // 2]
    right_half = core[:, w_core // 2 :]

    left_brightness = _trimmed_mean(left_half)
    right_brightness = _trimmed_mean(right_half)
    balance_diff = abs(left_brightness - right_brightness)
    balance_ratio = balance_diff / max(brightness, 1.0)

    reasons = []
    has_bad_lighting = False

    # Check brightness
    if brightness < min_brightness:
        has_bad_lighting = True
        reasons.append("too_dark")
    elif brightness > max_brightness:
        has_bad_lighting = True
        reasons.append("too_bright_washed_out")

    # Check contrast
    if contrast < min_contrast:
        has_bad_lighting = True
        reasons.append("low_contrast")

    # Check balance
    if balance_diff > balance_threshold and balance_ratio > max_balance_ratio:
        has_bad_lighting = True
        reasons.append("unbalanced_lighting")

    return {
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "left_brightness": round(left_brightness, 2),
        "right_brightness": round(right_brightness, 2),
        "balance_diff": round(balance_diff, 2),
        "balance_ratio": round(balance_ratio, 4),
        "region_used": region_used,
        "face_detected": face is not None,
        "has_bad_lighting": has_bad_lighting,
        "reasons": reasons,
    }


def run(
    images_dir: Path,
    min_brightness: float = 50.0,
    max_brightness: float = 200.0,
    min_contrast: float = 40.0,
    balance_threshold: float = 40.0,
    max_balance_ratio: float = 0.22,
) -> Dict[str, Any]:
    """
    Analyze all images in a directory for bad lighting.
    
    Args:
        images_dir: Root directory containing images
        min_brightness: Min brightness threshold (0-255)
        max_brightness: Max brightness threshold (0-255)
        min_contrast: Min contrast threshold (std dev)
        balance_threshold: Max allowed left-right brightness difference
    
    Returns:
        Analysis results with per-image metrics and aggregated stats
    """
    image_files = _collect_images(images_dir)
    analyzed_count = 0
    skipped_count = 0

    file_results: List[Dict[str, Any]] = []
    bad_lighting_count = 0

    reason_counts: Dict[str, int] = {
        "too_dark": 0,
        "too_bright_washed_out": 0,
        "low_contrast": 0,
        "unbalanced_lighting": 0,
    }

    for image_path in image_files:
        rgb = _load_rgb(image_path)
        if rgb is None:
            skipped_count += 1
            continue

        if rgb.shape[0] < 10 or rgb.shape[1] < 10:
            skipped_count += 1
            continue

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        rel_name = image_path.relative_to(images_dir).as_posix()

        metrics = _analyze_lighting(
            gray,
            min_brightness,
            max_brightness,
            min_contrast,
            balance_threshold,
            max_balance_ratio,
        )

        if metrics["has_bad_lighting"]:
            bad_lighting_count += 1
            for reason in metrics["reasons"]:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

        file_results.append(
            {
                "filename": rel_name,
                "brightness": metrics["brightness"],
                "contrast": metrics["contrast"],
                "left_brightness": metrics["left_brightness"],
                "right_brightness": metrics["right_brightness"],
                "balance_diff": metrics["balance_diff"],
                "balance_ratio": metrics["balance_ratio"],
                "region_used": metrics["region_used"],
                "face_detected": metrics["face_detected"],
                "has_bad_lighting": metrics["has_bad_lighting"],
                "reasons": metrics["reasons"],
            }
        )
        analyzed_count += 1

    # Separate good and bad lighting files
    good_lighting = [f for f in file_results if not f["has_bad_lighting"]]
    bad_lighting = [f for f in file_results if f["has_bad_lighting"]]

    # Sort each by quality
    good_lighting.sort(key=lambda x: x["contrast"], reverse=True)
    bad_lighting.sort(key=lambda x: x.get("brightness", 0))

    return {
        "success": True,
        "analyzedCount": analyzed_count,
        "skippedCount": skipped_count,
        "goodLightingCount": len(good_lighting),
        "badLightingCount": bad_lighting_count,
        "reasonCounts": reason_counts,
        "thresholds": {
            "min_brightness": min_brightness,
            "max_brightness": max_brightness,
            "min_contrast": min_contrast,
            "balance_threshold": balance_threshold,
            "max_balance_ratio": max_balance_ratio,
        },
        "goodLightingFiles": good_lighting,
        "badLightingFiles": bad_lighting,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze images for bad lighting using simple tunable thresholds")
    parser.add_argument("--imagesDir", required=True, help="Absolute path to images directory")
    parser.add_argument("--minBrightness", type=float, default=50.0, help="Min brightness (0-255). Darker → bad lighting")
    parser.add_argument("--maxBrightness", type=float, default=200.0, help="Max brightness (0-255). Brighter → washed out")
    parser.add_argument("--minContrast", type=float, default=40.0, help="Min contrast (std dev). Lower → flat/no detail")
    parser.add_argument("--balanceThreshold", type=float, default=40.0, help="Max L-R brightness diff. Higher → unbalanced")
    parser.add_argument("--maxBalanceRatio", type=float, default=0.22, help="Max relative L-R diff ratio. Higher → unbalanced")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    images_dir = Path(args.imagesDir).resolve()

    if not images_dir.exists() or not images_dir.is_dir():
        print(json.dumps({"success": False, "error": "imagesDir not found"}))
        return 2

    try:
        result = run(
            images_dir,
            min_brightness=args.minBrightness,
            max_brightness=args.maxBrightness,
            min_contrast=args.minContrast,
            balance_threshold=args.balanceThreshold,
            max_balance_ratio=args.maxBalanceRatio,
        )
        print(json.dumps(result))
        return 0
    except Exception as ex:
        print(json.dumps({"success": False, "error": f"Lighting analysis failed: {ex}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


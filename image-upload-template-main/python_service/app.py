from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import rawpy
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Blur Analysis Service", version="1.0.0")

VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".nef", ".dng", ".cr2"}
RAW_EXT = {".nef", ".dng", ".cr2"}
VALID_MODES = {"very_blurry", "slightly_blurry", "acceptable", "very_sharp"}


class AnalyzeRequest(BaseModel):
    imagesDir: str
    qualityMode: str = "acceptable"


def _collect_images(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VALID_EXT:
            files.append(path)
    return files


def _resize_gray(image: np.ndarray, max_dim: int = 512) -> np.ndarray:
    h, w = image.shape[:2]
    if h < 3 or w < 3:
        return image
    scale = min(1.0, max_dim / float(max(h, w)))
    if scale == 1.0:
        return image
    new_w = max(3, int(w * scale))
    new_h = max(3, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _laplacian_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _tenengrad(gray: np.ndarray) -> float:
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def _local_contrast(gray: np.ndarray) -> float:
    return float(np.std(gray.astype(np.float32)))


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.array(values, dtype=np.float64), p))


def _norm_by_percentiles(value: float, p10: float, p90: float) -> float:
    if p90 <= p10:
        return 0.5
    x = (value - p10) / (p90 - p10)
    return float(np.clip(x, 0.0, 1.0))


def _label_from_blur_score(score: int) -> str:
    if score > 70:
        return "Very blurry"
    if score > 45:
        return "Slightly blurry"
    if score > 20:
        return "Acceptable"
    return "Very sharp"


def _mode_from_blur_score(score: int) -> str:
    if score > 70:
        return "very_blurry"
    if score > 45:
        return "slightly_blurry"
    if score > 20:
        return "acceptable"
    return "very_sharp"


def _analyze_single_image(images_dir: Path, file_path: Path) -> Optional[Dict[str, Any]]:
    ext = file_path.suffix.lower()
    img: Optional[np.ndarray] = None

    if ext in RAW_EXT:
        try:
            with rawpy.imread(str(file_path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            img = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        except Exception:
            img = None
    else:
        img = cv2.imread(str(file_path), cv2.IMREAD_GRAYSCALE)

    if img is None:
        return None

    gray = _resize_gray(img, max_dim=512)
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return None

    lap = _laplacian_variance(gray)
    ten = _tenengrad(gray)
    contrast = _local_contrast(gray)

    rel = file_path.relative_to(images_dir).as_posix()
    return {
        "filename": rel,
        "laplacian": lap,
        "tenengrad": ten,
        "contrast": contrast,
        "rawSharpness": lap,
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/analyze-folder")
def analyze_folder(body: AnalyzeRequest) -> Dict[str, Any]:
    images_dir = Path(body.imagesDir).resolve()
    quality_mode = body.qualityMode if body.qualityMode in VALID_MODES else "acceptable"

    if not images_dir.exists() or not images_dir.is_dir():
        raise HTTPException(status_code=404, detail="imagesDir not found")

    image_files = _collect_images(images_dir)
    analyzed_count = 0
    skipped_count = 0

    raw_entries: List[Dict[str, Any]] = []
    lap_values: List[float] = []
    ten_values: List[float] = []
    contrast_values: List[float] = []

    max_workers = min(16, max(2, (os.cpu_count() or 4)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_analyze_single_image, images_dir, file_path) for file_path in image_files]
        for future in as_completed(futures):
            entry = future.result()
            if entry is None:
                skipped_count += 1
                continue

            raw_entries.append(entry)
            lap_values.append(float(entry["laplacian"]))
            ten_values.append(float(entry["tenengrad"]))
            contrast_values.append(float(entry["contrast"]))
            analyzed_count += 1

    lap_p10, lap_p90 = _percentile(lap_values, 10), _percentile(lap_values, 90)
    ten_p10, ten_p90 = _percentile(ten_values, 10), _percentile(ten_values, 90)
    con_p10, con_p90 = _percentile(contrast_values, 10), _percentile(contrast_values, 90)

    buckets = {
        "Very blurry": 0,
        "Slightly blurry": 0,
        "Acceptable": 0,
        "Very sharp": 0,
    }

    selected_files: List[str] = []
    selected_file_scores: List[Dict[str, Any]] = []
    file_scores: List[Dict[str, Any]] = []

    for entry in raw_entries:
        lap_norm = _norm_by_percentiles(entry["laplacian"], lap_p10, lap_p90)
        ten_norm = _norm_by_percentiles(entry["tenengrad"], ten_p10, ten_p90)
        con_norm = _norm_by_percentiles(entry["contrast"], con_p10, con_p90)

        sharpness_score = 0.50 * lap_norm + 0.35 * ten_norm + 0.15 * con_norm
        sharpness_score = float(np.clip(sharpness_score, 0.0, 1.0))
        blur_score = int(round((1.0 - sharpness_score) * 100.0))

        label = _label_from_blur_score(blur_score)
        mode = _mode_from_blur_score(blur_score)
        buckets[label] += 1

        if mode == quality_mode:
            selected_files.append(entry["filename"])

        item = {
            "filename": entry["filename"],
            "rawSharpness": round(float(entry["rawSharpness"]), 2),
            "laplacian": round(float(entry["laplacian"]), 2),
            "tenengrad": round(float(entry["tenengrad"]), 2),
            "contrast": round(float(entry["contrast"]), 2),
            "blurScore": blur_score,
            "qualityLabel": label,
            "qualityMode": mode,
        }
        file_scores.append(item)
        if mode == quality_mode:
            selected_file_scores.append(item)

    file_scores.sort(key=lambda x: x["blurScore"], reverse=True)
    selected_file_scores.sort(key=lambda x: x["blurScore"], reverse=True)

    return {
        "success": True,
        "qualityMode": quality_mode,
        "totalImagesFound": len(image_files),
        "analyzedCount": analyzed_count,
        "skippedCount": skipped_count,
        "buckets": buckets,
        "calibration": {
            "laplacianP10": round(lap_p10, 2),
            "laplacianP90": round(lap_p90, 2),
            "tenengradP10": round(ten_p10, 2),
            "tenengradP90": round(ten_p90, 2),
            "contrastP10": round(con_p10, 2),
            "contrastP90": round(con_p90, 2),
        },
        "selectedCount": len(selected_files),
        "selectedFiles": selected_files,
        "selectedFileScores": selected_file_scores,
        "fileScores": file_scores,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=False)

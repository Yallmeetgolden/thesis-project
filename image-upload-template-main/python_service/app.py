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

try:
    import torch
except Exception:
    torch = None

app = FastAPI(title="Blur Analysis Service", version="1.0.0")

VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".nef", ".dng", ".cr2"}
RAW_EXT = {".nef", ".dng", ".cr2"}
VALID_MODES = {"very_blurry", "slightly_blurry", "acceptable", "very_sharp"}
TORCH_AVAILABLE = torch is not None

_MODEL_CACHE: Dict[str, Any] = {
    "loaded": False,
    "model": None,
    "path": None,
    "error": None,
}


class AnalyzeRequest(BaseModel):
    imagesDir: str
    qualityMode: str = "acceptable"
    useDeepLearning: bool = True
    deepLearningWeight: float = 0.65


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


def _estimate_noise_sigma(gray: np.ndarray) -> float:
    gray_f = gray.astype(np.float32)
    lap = cv2.Laplacian(gray_f, cv2.CV_32F, ksize=3)
    return float(np.median(np.abs(lap)) / 0.6745) if lap.size else 0.0


def _enhance_low_light(gray: np.ndarray) -> np.ndarray:
    denoised = cv2.fastNlMeansDenoising(gray, None, h=7, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    return enhanced


def _brenner_gradient(gray: np.ndarray) -> float:
    gray64 = gray.astype(np.float64)
    if gray64.shape[0] < 3 or gray64.shape[1] < 3:
        return 0.0
    diff_x = gray64[:, 2:] - gray64[:, :-2]
    diff_y = gray64[2:, :] - gray64[:-2, :]
    score_x = np.mean(diff_x * diff_x) if diff_x.size else 0.0
    score_y = np.mean(diff_y * diff_y) if diff_y.size else 0.0
    return float((score_x + score_y) / 2.0)


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
    # Tuned boundaries based on user-provided sample categories.
    if score > 60:
        return "Very blurry"
    if score > 30:
        return "Slightly blurry"
    if score > 8:
        return "Acceptable"
    return "Very sharp"


def _mode_from_blur_score(score: int) -> str:
    if score > 60:
        return "very_blurry"
    if score > 30:
        return "slightly_blurry"
    if score > 8:
        return "acceptable"
    return "very_sharp"


def _get_model_path() -> Path:
    env_path = os.getenv("BLUR_MODEL_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent / "models" / "blur_classifier.pt"


def _get_torch_blur_model() -> Optional[Any]:
    if not TORCH_AVAILABLE:
        _MODEL_CACHE["loaded"] = True
        _MODEL_CACHE["model"] = None
        _MODEL_CACHE["error"] = "PyTorch is not installed"
        return None

    if _MODEL_CACHE["loaded"]:
        return _MODEL_CACHE["model"]

    model_path = _get_model_path()
    _MODEL_CACHE["path"] = str(model_path)

    if not model_path.exists():
        _MODEL_CACHE["loaded"] = True
        _MODEL_CACHE["model"] = None
        _MODEL_CACHE["error"] = f"Model not found at {model_path}"
        return None

    try:
        model = torch.jit.load(str(model_path), map_location="cpu")
        model.eval()
        _MODEL_CACHE["loaded"] = True
        _MODEL_CACHE["model"] = model
        _MODEL_CACHE["error"] = None
        return model
    except Exception as ex:
        _MODEL_CACHE["loaded"] = True
        _MODEL_CACHE["model"] = None
        _MODEL_CACHE["error"] = f"Model load failed: {ex}"
        return None


def _prepare_tensor_from_rgb(rgb: np.ndarray) -> Optional[Any]:
    if not TORCH_AVAILABLE:
        return None
    try:
        resized = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
        arr = resized.astype(np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))
        tensor = torch.from_numpy(arr)
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        tensor = (tensor - mean) / std
        return tensor
    except Exception:
        return None


def _extract_sharp_probability(output: Any) -> float:
    if not TORCH_AVAILABLE:
        return 0.5

    if isinstance(output, (list, tuple)) and len(output) > 0:
        output = output[0]

    if not torch.is_tensor(output):
        return 0.5

    if output.dim() == 2:
        if output.size(1) >= 2:
            probs = torch.softmax(output, dim=1)
            return float(probs[:, 1].item())
        if output.size(1) == 1:
            return float(torch.sigmoid(output[:, 0]).item())

    if output.dim() == 1:
        if output.numel() >= 2:
            probs = torch.softmax(output, dim=0)
            return float(probs[1].item())
        if output.numel() == 1:
            return float(torch.sigmoid(output[0]).item())

    return 0.5


def _run_deep_inference(raw_entries: List[Dict[str, Any]], model: Any) -> int:
    if not TORCH_AVAILABLE or model is None:
        return 0

    indexed_tensors: List[tuple[int, Any]] = []
    for idx, entry in enumerate(raw_entries):
        rgb = entry.get("rgbForModel")
        if rgb is None:
            continue
        t = _prepare_tensor_from_rgb(rgb)
        if t is None:
            continue
        indexed_tensors.append((idx, t))

    if not indexed_tensors:
        return 0

    batch_size = 24
    applied = 0
    with torch.no_grad():
        for start in range(0, len(indexed_tensors), batch_size):
            chunk = indexed_tensors[start : start + batch_size]
            batch = torch.stack([item[1] for item in chunk], dim=0)
            outputs = model(batch)

            if isinstance(outputs, (list, tuple)):
                outputs = outputs[0]

            if not torch.is_tensor(outputs):
                for idx, _ in chunk:
                    raw_entries[idx]["deepSharpProb"] = 0.5
                    raw_entries[idx]["deepBlurProb"] = 0.5
                    applied += 1
                continue

            if outputs.dim() == 1:
                outputs = outputs.unsqueeze(0)

            if outputs.size(0) != len(chunk):
                for idx, _ in chunk:
                    raw_entries[idx]["deepSharpProb"] = 0.5
                    raw_entries[idx]["deepBlurProb"] = 0.5
                    applied += 1
                continue

            for row_idx, (entry_idx, _) in enumerate(chunk):
                out_row = outputs[row_idx]
                sharp_prob = _extract_sharp_probability(out_row)
                sharp_prob = float(np.clip(sharp_prob, 0.0, 1.0))
                raw_entries[entry_idx]["deepSharpProb"] = sharp_prob
                raw_entries[entry_idx]["deepBlurProb"] = float(1.0 - sharp_prob)
                applied += 1

    return applied


def _analyze_single_image(images_dir: Path, file_path: Path) -> Optional[Dict[str, Any]]:
    ext = file_path.suffix.lower()
    rgb: Optional[np.ndarray] = None
    gray: Optional[np.ndarray] = None

    if ext in RAW_EXT:
        try:
            with rawpy.imread(str(file_path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        except Exception:
            rgb = None
            gray = None
    else:
        bgr = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
        if bgr is not None:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    if gray is None:
        return None

    gray_small = _resize_gray(gray, max_dim=512)
    if gray_small.shape[0] < 3 or gray_small.shape[1] < 3:
        return None

    brightness = float(np.mean(gray_small))
    noise_sigma = _estimate_noise_sigma(gray_small)

    enhanced_gray = _enhance_low_light(gray_small) if brightness < 90.0 else gray_small

    lap = _laplacian_variance(enhanced_gray)
    ten = _tenengrad(enhanced_gray)
    brenner = _brenner_gradient(enhanced_gray)
    contrast = _local_contrast(enhanced_gray)

    rel = file_path.relative_to(images_dir).as_posix()
    return {
        "filename": rel,
        "laplacian": lap,
        "tenengrad": ten,
        "brenner": brenner,
        "contrast": contrast,
        "rawSharpness": lap,
        "brightness": brightness,
        "noiseSigma": noise_sigma,
        "lowLightFlag": brightness < 90.0,
        "rgbForModel": rgb,
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/analyze-folder")
def analyze_folder(body: AnalyzeRequest) -> Dict[str, Any]:
    images_dir = Path(body.imagesDir).resolve()
    quality_mode = body.qualityMode if body.qualityMode in VALID_MODES else "acceptable"
    use_deep_learning = bool(body.useDeepLearning)
    deep_weight = float(np.clip(body.deepLearningWeight, 0.0, 0.95))

    if not images_dir.exists() or not images_dir.is_dir():
        raise HTTPException(status_code=404, detail="imagesDir not found")

    image_files = _collect_images(images_dir)
    analyzed_count = 0
    skipped_count = 0

    raw_entries: List[Dict[str, Any]] = []
    lap_values: List[float] = []
    ten_values: List[float] = []
    brenner_values: List[float] = []
    contrast_values: List[float] = []
    brightness_values: List[float] = []
    noise_values: List[float] = []

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
            brenner_values.append(float(entry["brenner"]))
            contrast_values.append(float(entry["contrast"]))
            brightness_values.append(float(entry["brightness"]))
            noise_values.append(float(entry["noiseSigma"]))
            analyzed_count += 1

    lap_p10, lap_p90 = _percentile(lap_values, 10), _percentile(lap_values, 90)
    ten_p10, ten_p90 = _percentile(ten_values, 10), _percentile(ten_values, 90)
    brenner_p10, brenner_p90 = _percentile(brenner_values, 10), _percentile(brenner_values, 90)
    con_p10, con_p90 = _percentile(contrast_values, 10), _percentile(contrast_values, 90)
    noise_p10, noise_p90 = _percentile(noise_values, 10), _percentile(noise_values, 90)
    brightness_p10, brightness_p90 = _percentile(brightness_values, 10), _percentile(brightness_values, 90)

    model = _get_torch_blur_model() if use_deep_learning else None
    deep_applied_count = _run_deep_inference(raw_entries, model) if model is not None else 0
    model_used = "hybrid" if deep_applied_count > 0 else "classical"

    buckets = {
        "Very blurry": 0,
        "Slightly blurry": 0,
        "Acceptable": 0,
        "Very sharp": 0,
    }

    selected_files: List[str] = []
    selected_file_scores: List[Dict[str, Any]] = []
    file_scores: List[Dict[str, Any]] = []
    sharpness_scores_for_dynamic: List[float] = []

    interim_items: List[Dict[str, Any]] = []

    for entry in raw_entries:
        lap_norm = _norm_by_percentiles(entry["laplacian"], lap_p10, lap_p90)
        ten_norm = _norm_by_percentiles(entry["tenengrad"], ten_p10, ten_p90)
        brenner_norm = _norm_by_percentiles(entry["brenner"], brenner_p10, brenner_p90)
        con_norm = _norm_by_percentiles(entry["contrast"], con_p10, con_p90)
        noise_norm = _norm_by_percentiles(entry["noiseSigma"], noise_p10, noise_p90)

        is_low_light = bool(entry.get("lowLightFlag", False))
        if is_low_light:
            w_lap, w_ten, w_brenner = 0.22, 0.43, 0.35
        else:
            w_lap, w_ten, w_brenner = 0.40, 0.40, 0.20

        classical_sharpness = w_lap * lap_norm + w_ten * ten_norm + w_brenner * brenner_norm
        noise_penalty = 1.0 - (0.12 * noise_norm)
        classical_sharpness = classical_sharpness * float(np.clip(noise_penalty, 0.70, 1.0))
        # Preserve subject sharpness in depth-of-field scenes by boosting when gradients are strong.
        texture_presence = (0.60 * ten_norm) + (0.40 * brenner_norm)
        subject_boost = max(0.0, texture_presence - 0.55) * 0.18 + max(0.0, con_norm - 0.50) * 0.06
        classical_sharpness += subject_boost
        classical_sharpness = float(np.clip(classical_sharpness, 0.0, 1.0))

        deep_sharp = entry.get("deepSharpProb")
        if deep_sharp is not None:
            sharpness_score = float((1.0 - deep_weight) * classical_sharpness + deep_weight * float(deep_sharp))
        else:
            sharpness_score = classical_sharpness

        sharpness_scores_for_dynamic.append(sharpness_score)

        interim_items.append(
            {
                "entry": entry,
                "lapNorm": lap_norm,
                "tenNorm": ten_norm,
                "brennerNorm": brenner_norm,
                "contrastNorm": con_norm,
                "noiseNorm": noise_norm,
                "isLowLight": is_low_light,
                "classicalSharpnessFloat": classical_sharpness,
                "deepSharpProb": deep_sharp,
                "sharpnessScoreFloat": sharpness_score,
            }
        )

    mean_sharpness_score = float(np.mean(sharpness_scores_for_dynamic)) if sharpness_scores_for_dynamic else 0.0
    dynamic_sharpness_threshold = float(np.clip(mean_sharpness_score * 0.60, 0.05, 0.95))

    for row in interim_items:
        entry = row["entry"]
        sharpness_score = row["sharpnessScoreFloat"]
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
            "brenner": round(float(entry["brenner"]), 2),
            "contrast": round(float(entry["contrast"]), 2),
            "lapNorm": round(float(row["lapNorm"]), 4),
            "tenNorm": round(float(row["tenNorm"]), 4),
            "brennerNorm": round(float(row["brennerNorm"]), 4),
            "noiseNorm": round(float(row["noiseNorm"]), 4),
            "brightness": round(float(entry["brightness"]), 2),
            "noiseSigma": round(float(entry["noiseSigma"]), 2),
            "isLowLight": bool(row["isLowLight"]),
            "classicalSharpnessScore": round(float(row["classicalSharpnessFloat"] * 100.0), 2),
            "deepSharpProb": round(float(row["deepSharpProb"]), 4) if row["deepSharpProb"] is not None else None,
            "finalSharpnessScore": round(float(sharpness_score * 100.0), 2),
            "blurScore": blur_score,
            "binaryStatus": "Sharp" if sharpness_score >= dynamic_sharpness_threshold else "Blurry",
            "qualityLabel": label,
            "qualityMode": mode,
        }
        file_scores.append(item)
        if mode == quality_mode:
            selected_file_scores.append(item)

    file_scores.sort(key=lambda x: x["blurScore"], reverse=True)
    selected_file_scores.sort(key=lambda x: x["blurScore"], reverse=True)

    for entry in raw_entries:
        if "rgbForModel" in entry:
            entry.pop("rgbForModel", None)

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
            "brennerP10": round(brenner_p10, 2),
            "brennerP90": round(brenner_p90, 2),
            "contrastP10": round(con_p10, 2),
            "contrastP90": round(con_p90, 2),
            "noiseP10": round(noise_p10, 2),
            "noiseP90": round(noise_p90, 2),
            "brightnessP10": round(brightness_p10, 2),
            "brightnessP90": round(brightness_p90, 2),
            "meanSharpnessScore": round(mean_sharpness_score * 100.0, 2),
            "dynamicSharpnessThreshold": round(dynamic_sharpness_threshold * 100.0, 2),
            "modelUsed": model_used,
            "deepLearningEnabled": use_deep_learning,
            "deepLearningWeight": round(deep_weight, 3),
            "deepLearningAppliedCount": int(deep_applied_count),
            "modelPath": _MODEL_CACHE.get("path"),
            "modelStatus": "loaded" if deep_applied_count > 0 else (_MODEL_CACHE.get("error") or "not-used"),
        },
        "selectedCount": len(selected_files),
        "selectedFiles": selected_files,
        "selectedFileScores": selected_file_scores,
        "fileScores": file_scores,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=False)

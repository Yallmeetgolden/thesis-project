from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import rawpy
except Exception:
    rawpy = None

import torch
import torch.nn as nn
from torchvision import models, transforms
from torchvision.models import ResNet50_Weights

VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".nef", ".dng", ".cr2"}
RAW_EXT = {".nef", ".dng", ".cr2"}


class _EmbeddingNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        backbone = models.resnet50(weights=ResNet50_Weights.IMAGENET1K_V2)
        self.features = nn.Sequential(*list(backbone.children())[:-1])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = torch.flatten(x, 1)
        return x


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
        if rawpy is None:
            return None
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


def _build_transform():
    return transforms.Compose(
        [
            transforms.ToPILImage(),
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )


def _cosine_similarity_matrix(emb: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-12, None)
    normed = emb / norms
    return np.matmul(normed, normed.T)


def _build_groups(n: int, pairs: List[Tuple[int, int]]) -> List[List[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, j in pairs:
        union(i, j)

    buckets: Dict[int, List[int]] = {}
    for i in range(n):
        r = find(i)
        buckets.setdefault(r, []).append(i)

    groups = [sorted(v) for v in buckets.values() if len(v) >= 2]
    groups.sort(key=len, reverse=True)
    return groups


def run(images_dir: Path, threshold: float, max_pairs: int) -> Dict[str, object]:
    image_files = _collect_images(images_dir)
    transform = _build_transform()
    model = _EmbeddingNet().eval()

    tensors: List[torch.Tensor] = []
    rel_names: List[str] = []
    skipped = 0

    for p in image_files:
        rgb = _load_rgb(p)
        if rgb is None:
            skipped += 1
            continue
        try:
            t = transform(rgb)
            tensors.append(t)
            rel_names.append(p.relative_to(images_dir).as_posix())
        except Exception:
            skipped += 1

    if not tensors:
        return {
            "success": True,
            "model": "resnet50_embeddings",
            "threshold": threshold,
            "analyzedCount": 0,
            "skippedCount": skipped,
            "duplicatePairs": [],
            "duplicateGroups": [],
            "duplicatesFound": 0,
            "uniqueCount": 0,
        }

    batch_size = 16
    feats: List[torch.Tensor] = []
    with torch.no_grad():
        for start in range(0, len(tensors), batch_size):
            chunk = torch.stack(tensors[start : start + batch_size], dim=0)
            out = model(chunk)
            feats.append(out.cpu())

    emb = torch.cat(feats, dim=0).numpy().astype(np.float32)
    sim = _cosine_similarity_matrix(emb)

    pair_idx: List[Tuple[int, int]] = []
    pair_data: List[Tuple[int, int, float]] = []

    n = len(rel_names)
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sim[i, j])
            if s >= threshold:
                pair_idx.append((i, j))
                pair_data.append((i, j, s))

    pair_data.sort(key=lambda x: x[2], reverse=True)
    pair_data = pair_data[:max_pairs]

    groups_idx = _build_groups(n, pair_idx)

    duplicate_pairs = [
        {
            "fileA": rel_names[i],
            "fileB": rel_names[j],
            "similarity": round(float(s), 4),
        }
        for i, j, s in pair_data
    ]

    duplicate_groups = [[rel_names[idx] for idx in group] for group in groups_idx]

    duplicate_name_set = set()
    for group in duplicate_groups:
        for name in group:
            duplicate_name_set.add(name)

    return {
        "success": True,
        "model": "resnet50_embeddings",
        "threshold": threshold,
        "analyzedCount": len(rel_names),
        "skippedCount": skipped,
        "duplicatePairs": duplicate_pairs,
        "duplicateGroups": duplicate_groups,
        "duplicatesFound": len(duplicate_name_set),
        "uniqueCount": len(rel_names) - len(duplicate_name_set),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Duplicate pose/image detection via ResNet embeddings")
    parser.add_argument("--imagesDir", required=True, help="Absolute path to extracted images directory")
    parser.add_argument("--threshold", type=float, default=0.92, help="Cosine similarity threshold")
    parser.add_argument("--maxPairs", type=int, default=200, help="Max duplicate pairs to include in output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    images_dir = Path(args.imagesDir).resolve()
    threshold = float(np.clip(args.threshold, 0.70, 0.999))
    max_pairs = max(1, int(args.maxPairs))

    if not images_dir.exists() or not images_dir.is_dir():
        print(json.dumps({"success": False, "error": "imagesDir not found"}))
        return 2

    try:
        result = run(images_dir, threshold, max_pairs)
        print(json.dumps(result))
        return 0
    except Exception as ex:
        print(json.dumps({"success": False, "error": f"Duplicate analysis failed: {ex}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

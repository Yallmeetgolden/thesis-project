from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

VALID_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".nef", ".dng", ".cr2"}
RAW_EXT = {".nef", ".dng", ".cr2"}


def load_image_rgb(path: Path):
    ext = path.suffix.lower()
    if ext in RAW_EXT:
        try:
            import rawpy

            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            return rgb
        except Exception:
            return None

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


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


def random_blur(img: np.ndarray) -> np.ndarray:
    out = img.copy()
    if random.random() < 0.65:
        sigma = random.uniform(0.8, 3.5)
        k = int(max(3, round(sigma * 4) | 1))
        out = cv2.GaussianBlur(out, (k, k), sigmaX=sigma, sigmaY=sigma)
    if random.random() < 0.55:
        out = motion_blur(out, ksize=random.randint(5, 21), angle=random.uniform(0, 180))
    if random.random() < 0.4:
        noise = np.random.normal(0, random.uniform(2, 12), out.shape).astype(np.float32)
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if random.random() < 0.35:
        gamma = random.uniform(1.2, 2.2)
        lut = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)]).astype(np.uint8)
        out = cv2.LUT(out, lut)
    return out


def preprocess(img: np.ndarray) -> torch.Tensor:
    img = cv2.resize(img, (224, 224), interpolation=cv2.INTER_AREA)
    arr = img.astype(np.float32) / 255.0
    arr = np.transpose(arr, (2, 0, 1))
    x = torch.from_numpy(arr)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
    return (x - mean) / std


class SyntheticBlurDataset(Dataset):
    def __init__(self, image_paths: List[Path], samples: int):
        self.image_paths = image_paths
        self.samples = samples

    def __len__(self):
        return self.samples

    def __getitem__(self, idx):
        path = random.choice(self.image_paths)
        rgb = load_image_rgb(path)
        if rgb is None:
            x = torch.zeros(3, 224, 224)
            y = torch.tensor(0, dtype=torch.long)
            return x, y

        h, w = rgb.shape[:2]
        crop_size = random.randint(224, min(640, h, w)) if min(h, w) >= 224 else min(h, w)
        if crop_size >= 32 and h >= crop_size and w >= crop_size:
            y0 = random.randint(0, h - crop_size)
            x0 = random.randint(0, w - crop_size)
            patch = rgb[y0 : y0 + crop_size, x0 : x0 + crop_size]
        else:
            patch = rgb

        if random.random() < 0.5:
            img = random_blur(patch)
            label = 0
        else:
            img = patch
            if random.random() < 0.25:
                alpha = random.uniform(0.85, 1.15)
                beta = random.uniform(-8, 8)
                img = np.clip(img.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)
            label = 1

        return preprocess(img), torch.tensor(label, dtype=torch.long)


class SmallBlurCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, stride=2, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, 3, stride=2, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 128, 3, stride=2, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, 192, 3, stride=2, padding=1),
            nn.BatchNorm2d(192),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Linear(192, 2)

    def forward(self, x):
        f = self.features(x).flatten(1)
        return self.classifier(f)


def collect_images(images_dir: Path) -> List[Path]:
    files = [p for p in images_dir.rglob("*") if p.is_file() and p.suffix.lower() in VALID_EXT]
    return files


def train(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    images_dir = Path(args.images_dir).resolve()
    if not images_dir.exists():
        raise RuntimeError(f"images_dir not found: {images_dir}")

    paths = collect_images(images_dir)
    if len(paths) < 6:
        raise RuntimeError(f"Need at least 6 images to bootstrap model, found {len(paths)}")

    random.shuffle(paths)
    split = int(len(paths) * 0.85)
    train_paths = paths[:split]
    val_paths = paths[split:] if len(paths) - split >= 5 else paths[max(0, len(paths) - 10) :]

    train_samples = min(args.train_samples, max(300, len(train_paths) * 120))
    val_samples = min(args.val_samples, max(120, len(val_paths) * 60))

    train_ds = SyntheticBlurDataset(train_paths, samples=train_samples)
    val_ds = SyntheticBlurDataset(val_paths, samples=val_samples)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    device = torch.device("cpu")
    model = SmallBlurCNN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    best_acc = -1.0
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        tr_total = 0
        tr_correct = 0
        tr_loss = 0.0

        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()

            preds = torch.argmax(logits, dim=1)
            tr_total += y.size(0)
            tr_correct += (preds == y).sum().item()
            tr_loss += float(loss.item()) * y.size(0)

        model.eval()
        va_total = 0
        va_correct = 0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                logits = model(x)
                preds = torch.argmax(logits, dim=1)
                va_total += y.size(0)
                va_correct += (preds == y).sum().item()

        tr_acc = tr_correct / max(1, tr_total)
        va_acc = va_correct / max(1, va_total)
        tr_avg_loss = tr_loss / max(1, tr_total)
        print(f"Epoch {epoch}/{args.epochs} train_loss={tr_avg_loss:.4f} train_acc={tr_acc:.4f} val_acc={va_acc:.4f}")

        if va_acc > best_acc:
            best_acc = va_acc
            best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training failed")

    model.load_state_dict(best_state)
    model.eval()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    state_path = out_dir / "blur_classifier_state_dict.pth"
    torch.save({"state_dict": model.state_dict(), "best_val_acc": best_acc}, state_path)

    example = torch.randn(1, 3, 224, 224)
    scripted = torch.jit.trace(model, example)
    model_path = out_dir / "blur_classifier.pt"
    scripted.save(str(model_path))

    metrics = {
        "best_val_acc": best_acc,
        "train_images": len(train_paths),
        "val_images": len(val_paths),
        "train_samples": train_samples,
        "val_samples": val_samples,
        "model_path": str(model_path),
    }
    (out_dir / "synthetic_training_metrics.json").write_text(str(metrics), encoding="utf-8")

    print("Saved model:", model_path)
    print("Best synthetic val acc:", round(best_acc, 4))


def parse_args():
    parser = argparse.ArgumentParser(description="Train a bootstrap blur model using synthetic blur generation")
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent / "models"))
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--train-samples", type=int, default=2500)
    parser.add_argument("--val-samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())

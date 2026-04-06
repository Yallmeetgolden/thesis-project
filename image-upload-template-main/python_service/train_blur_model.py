from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms
from torchvision.models import MobileNet_V2_Weights


def build_transforms(train: bool):
    if train:
        return transforms.Compose(
            [
                transforms.Resize((256, 256)),
                transforms.RandomResizedCrop(224, scale=(0.8, 1.0)),
                transforms.RandomHorizontalFlip(),
                transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
    return transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )


def resolve_dirs(data_dir: Path) -> Tuple[Path, Path]:
    train_dir = data_dir / "train"
    val_dir = data_dir / "val"
    if train_dir.exists() and val_dir.exists():
        return train_dir, val_dir
    return data_dir, data_dir


def validate_classes(class_to_idx: Dict[str, int]) -> None:
    required = {"blurry", "sharp"}
    found = set(class_to_idx.keys())
    if not required.issubset(found):
        raise RuntimeError(
            f"Dataset must contain class folders named blurry and sharp. Found: {sorted(found)}"
        )


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device):
    model.eval()
    total = 0
    correct = 0
    loss_sum = 0.0
    criterion = nn.CrossEntropyLoss()

    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            preds = torch.argmax(outputs, dim=1)

            total += targets.size(0)
            correct += (preds == targets).sum().item()
            loss_sum += float(loss.item()) * targets.size(0)

    if total == 0:
        return 0.0, 0.0
    return loss_sum / total, correct / total


def train(args):
    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        raise RuntimeError(f"Data directory does not exist: {data_dir}")

    train_dir, val_dir = resolve_dirs(data_dir)

    train_dataset = datasets.ImageFolder(train_dir, transform=build_transforms(train=True))
    val_dataset = datasets.ImageFolder(val_dir, transform=build_transforms(train=False))

    validate_classes(train_dataset.class_to_idx)

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=torch.cuda.is_available(),
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=torch.cuda.is_available(),
    )

    weights = MobileNet_V2_Weights.IMAGENET1K_V2
    model = models.mobilenet_v2(weights=weights)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, 2)

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model = model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    best_acc = -1.0
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        running_correct = 0
        running_total = 0

        for inputs, targets in train_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)

            optimizer.zero_grad(set_to_none=True)
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

            preds = torch.argmax(outputs, dim=1)
            running_total += targets.size(0)
            running_correct += (preds == targets).sum().item()
            running_loss += float(loss.item()) * targets.size(0)

        train_loss = running_loss / max(1, running_total)
        train_acc = running_correct / max(1, running_total)
        val_loss, val_acc = evaluate(model, val_loader, device)

        print(
            f"Epoch {epoch}/{args.epochs} | train_loss={train_loss:.4f} train_acc={train_acc:.4f} "
            f"| val_loss={val_loss:.4f} val_acc={val_acc:.4f}"
        )

        if val_acc > best_acc:
            best_acc = val_acc
            best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training failed: no model state captured")

    model.load_state_dict(best_state)
    model = model.cpu().eval()

    model_dir = Path(args.model_dir).resolve()
    model_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = model_dir / "blur_classifier_state_dict.pth"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "class_to_idx": train_dataset.class_to_idx,
            "best_val_acc": best_acc,
        },
        checkpoint_path,
    )

    example = torch.randn(1, 3, 224, 224)
    scripted = torch.jit.trace(model, example)
    scripted_path = model_dir / "blur_classifier.pt"
    scripted.save(str(scripted_path))

    metrics_path = model_dir / "training_metrics.json"
    metrics = {
        "best_val_acc": best_acc,
        "train_samples": len(train_dataset),
        "val_samples": len(val_dataset),
        "class_to_idx": train_dataset.class_to_idx,
        "checkpoint_path": str(checkpoint_path),
        "scripted_model_path": str(scripted_path),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"Saved: {scripted_path}")
    print(f"Validation accuracy: {best_acc:.4f}")


def parse_args():
    parser = argparse.ArgumentParser(description="Train blur classifier and export TorchScript model")
    parser.add_argument("--data-dir", required=True, help="Dataset path with class folders blurry/sharp")
    parser.add_argument(
        "--model-dir",
        default=str(Path(__file__).resolve().parent / "models"),
        help="Output directory for model files",
    )
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--cpu", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(args)

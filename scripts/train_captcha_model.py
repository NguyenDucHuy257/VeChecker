"""Fine-tune MobileNetV3-Small for fixed-length, case-sensitive CAPTCHA OCR."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
import string
from typing import Any


CHARSET = string.digits + string.ascii_uppercase + string.ascii_lowercase
LABEL_LENGTH = 4
INPUT_HEIGHT = 35
INPUT_WIDTH = 120
CROP_SIZE = 64
# The source renderer places four 20 px cells in the left ~84 px of a 120 px
# canvas. Two pixels of surrounding context preserve anti-aliased edge strokes.
CROP_BOUNDS = ((4, 26), (24, 46), (44, 66), (64, 86))


@dataclass(frozen=True, slots=True)
class Sample:
    path: Path
    label: str


@dataclass(frozen=True, slots=True)
class Metrics:
    loss: float
    character_accuracy: float
    exact_accuracy: float


def load_samples(dataset_dir: Path) -> list[Sample]:
    manifest = dataset_dir / "labels.tsv"
    if not manifest.is_file():
        raise ValueError(f"Không thấy manifest: {manifest}")

    samples: list[Sample] = []
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["filename", "label"]:
            raise ValueError("labels.tsv phải có hai cột: filename và label")
        for line, row in enumerate(reader, 2):
            relative = Path(row["filename"])
            path = (dataset_dir / relative).resolve()
            root = dataset_dir.resolve()
            if root not in path.parents or not path.is_file():
                raise ValueError(f"Ảnh không hợp lệ tại dòng {line}: {relative}")
            label = row["label"]
            if len(label) != LABEL_LENGTH or any(char not in CHARSET for char in label):
                raise ValueError(f"Nhãn không hợp lệ tại dòng {line}: {label!r}")
            samples.append(Sample(path, label))
    if not samples:
        raise ValueError("Dataset không có mẫu nào")
    return samples


def split_samples(
    samples: list[Sample], *, seed: int, validation_ratio: float, test_ratio: float
) -> tuple[list[Sample], list[Sample], list[Sample]]:
    """Split by label so duplicate labels cannot leak across partitions."""

    if validation_ratio <= 0 or test_ratio <= 0 or validation_ratio + test_ratio >= 1:
        raise ValueError("Tỉ lệ validation/test không hợp lệ")
    groups: dict[str, list[Sample]] = {}
    for sample in samples:
        groups.setdefault(sample.label, []).append(sample)
    labels = list(groups)
    random.Random(seed).shuffle(labels)

    validation_target = round(len(samples) * validation_ratio)
    test_target = round(len(samples) * test_ratio)
    validation: list[Sample] = []
    test: list[Sample] = []
    train: list[Sample] = []
    for label in labels:
        group = groups[label]
        if len(validation) < validation_target:
            validation.extend(group)
        elif len(test) < test_target:
            test.extend(group)
        else:
            train.extend(group)
    return train, validation, test


def import_training_stack() -> dict[str, Any]:
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, Dataset
        from torchvision import transforms
        from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu dependency train. Chạy: pip install -e '.[train]'"
        ) from exc
    return {
        "torch": torch,
        "nn": nn,
        "DataLoader": DataLoader,
        "Dataset": Dataset,
        "transforms": transforms,
        "weights": MobileNet_V3_Small_Weights,
        "mobilenet": mobilenet_v3_small,
    }


def build_components(
    stack: dict[str, Any], *, pretrained: bool, architecture: str = "spatial"
) -> tuple[Any, type[Any]]:
    torch = stack["torch"]
    nn = stack["nn"]
    functional = torch.nn.functional
    base = stack["mobilenet"](
        weights=stack["weights"].DEFAULT if pretrained else None
    )
    feature_dim = base.classifier[0].in_features

    class CharacterCropsMobileNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = base.features
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.dropout = nn.Dropout(0.2)
            self.heads = nn.ModuleList(
                nn.Linear(feature_dim, len(CHARSET)) for _ in range(LABEL_LENGTH)
            )

        def forward(self, images: Any) -> Any:
            # Runtime contract is grayscale [B, 1, H, W]; pretrained backbone is RGB.
            batch = images.shape[0]
            crops = torch.cat(
                [
                    functional.interpolate(
                        images[:, :, :, left:right],
                        size=(CROP_SIZE, CROP_SIZE),
                        mode="bilinear",
                        align_corners=False,
                    )
                    for left, right in CROP_BOUNDS
                ],
                dim=0,
            )
            crops = crops.repeat(1, 3, 1, 1)
            mean = crops.new_tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1)
            std = crops.new_tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
            features = self.pool(self.features((crops - mean) / std)).flatten(1)
            features = features.view(LABEL_LENGTH, batch, feature_dim)
            return torch.stack(
                [self.heads[position](self.dropout(features[position]))
                 for position in range(LABEL_LENGTH)],
                dim=1,
            )

    class SpatialMobileNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = base.features
            self.pool = nn.AdaptiveAvgPool2d((1, LABEL_LENGTH))
            self.dropout = nn.Dropout(0.2)
            self.classifier = nn.Linear(feature_dim, len(CHARSET))

        def forward(self, images: Any) -> Any:
            images = images.repeat(1, 3, 1, 1)
            mean = images.new_tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1)
            std = images.new_tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
            features = self.features((images - mean) / std)
            features = self.pool(features).squeeze(2).transpose(1, 2)
            return self.classifier(self.dropout(features))

    class SharedCharacterCropsMobileNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = base.features
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.dropout = nn.Dropout(0.2)
            self.classifier = nn.Linear(feature_dim, len(CHARSET))

        def forward(self, images: Any) -> Any:
            batch = images.shape[0]
            crops = torch.cat(
                [
                    functional.interpolate(
                        images[:, :, :, left:right],
                        size=(CROP_SIZE, CROP_SIZE),
                        mode="bilinear",
                        align_corners=False,
                    )
                    for left, right in CROP_BOUNDS
                ],
                dim=0,
            )
            crops = crops.repeat(1, 3, 1, 1)
            mean = crops.new_tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1)
            std = crops.new_tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
            features = self.pool(self.features((crops - mean) / std)).flatten(1)
            logits = self.classifier(self.dropout(features))
            return logits.view(LABEL_LENGTH, batch, len(CHARSET)).transpose(0, 1)

    class CaptchaDataset(stack["Dataset"]):
        def __init__(self, rows: list[Sample], *, augment: bool) -> None:
            self.rows = rows
            ops: list[Any] = []
            if augment:
                ops.extend(
                    [
                        stack["transforms"].RandomAffine(
                            degrees=3, translate=(0.02, 0.04), fill=255
                        ),
                        stack["transforms"].ColorJitter(brightness=0.12, contrast=0.12),
                    ]
                )
            ops.extend(
                [
                    stack["transforms"].Resize((INPUT_HEIGHT, INPUT_WIDTH)),
                    stack["transforms"].ToTensor(),
                ]
            )
            self.transform = stack["transforms"].Compose(ops)

        def __len__(self) -> int:
            return len(self.rows)

        def __getitem__(self, index: int) -> tuple[Any, Any]:
            from PIL import Image

            sample = self.rows[index]
            with Image.open(sample.path) as source:
                image = self.transform(source.convert("L"))
            target = torch.tensor([CHARSET.index(char) for char in sample.label])
            return image, target

    models = {
        "spatial": SpatialMobileNet,
        "character-crops": CharacterCropsMobileNet,
        "character-crops-shared": SharedCharacterCropsMobileNet,
    }
    if architecture not in models:
        raise ValueError(f"Kiến trúc không hỗ trợ: {architecture}")
    return models[architecture](), CaptchaDataset


def run_epoch(
    model: Any, loader: Any, criterion: Any, *, device: Any, optimizer: Any | None
) -> Metrics:
    torch = import_training_stack()["torch"]
    training = optimizer is not None
    model.train(training)
    total_loss = total_chars = correct_chars = exact = total = 0
    for images, targets in loader:
        images, targets = images.to(device), targets.to(device)
        if training:
            optimizer.zero_grad(set_to_none=True)
        with torch.set_grad_enabled(training):
            logits = model(images)
            loss = criterion(logits.reshape(-1, len(CHARSET)), targets.reshape(-1))
            if training:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
        predictions = logits.argmax(dim=-1)
        batch = targets.shape[0]
        total_loss += float(loss.detach()) * batch
        correct_chars += int((predictions == targets).sum())
        total_chars += targets.numel()
        exact += int((predictions == targets).all(dim=1).sum())
        total += batch
    return Metrics(total_loss / total, correct_chars / total_chars, exact / total)


def export_onnx(model: Any, destination: Path, stack: dict[str, Any]) -> None:
    torch = stack["torch"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    model = model.to("cpu").eval()
    dummy = torch.zeros(1, 1, INPUT_HEIGHT, INPUT_WIDTH)
    torch.onnx.export(
        model,
        dummy,
        destination,
        input_names=["captcha"],
        output_names=["logits"],
        dynamic_axes={"captcha": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=18,
        dynamo=False,
    )
    metadata = {
        "input_width": INPUT_WIDTH,
        "input_height": INPUT_HEIGHT,
        "length": LABEL_LENGTH,
        "charset": CHARSET,
        "input_name": "captcha",
        "output_name": "logits",
    }
    destination.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("runtime/dataset"))
    parser.add_argument("--output", type=Path, default=Path("models/captcha/model.onnx"))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--warmup-epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--no-pretrained", action="store_true")
    parser.add_argument(
        "--architecture",
        choices=("spatial", "character-crops", "character-crops-shared"),
        default="character-crops",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.epochs <= 0 or args.batch_size <= 0 or args.warmup_epochs < 0:
        raise SystemExit("epochs/batch-size phải dương và warmup-epochs không được âm")
    stack = import_training_stack()
    torch = stack["torch"]
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    samples = load_samples(args.dataset)
    train, validation, test = split_samples(
        samples, seed=args.seed, validation_ratio=0.1, test_ratio=0.1
    )
    model, dataset_type = build_components(
        stack, pretrained=not args.no_pretrained, architecture=args.architecture
    )
    loaders = {
        "train": stack["DataLoader"](
            dataset_type(train, augment=True), batch_size=args.batch_size,
            shuffle=True, num_workers=args.workers
        ),
        "validation": stack["DataLoader"](
            dataset_type(validation, augment=False), batch_size=args.batch_size,
            num_workers=args.workers
        ),
        "test": stack["DataLoader"](
            dataset_type(test, augment=False), batch_size=args.batch_size,
            num_workers=args.workers
        ),
    }
    model.to(device)
    criterion = stack["nn"].CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max(1, args.epochs - args.warmup_epochs)
    )
    for parameter in model.features.parameters():
        parameter.requires_grad = args.warmup_epochs == 0

    checkpoint = args.output.with_suffix(".pt")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    best = (-math.inf, -math.inf, -math.inf)
    stale = 0
    history: list[dict[str, Any]] = []
    print(f"device={device} train={len(train)} validation={len(validation)} test={len(test)}")
    for epoch in range(1, args.epochs + 1):
        if epoch == args.warmup_epochs + 1:
            for parameter in model.features.parameters():
                parameter.requires_grad = True
        train_metrics = run_epoch(
            model, loaders["train"], criterion, device=device, optimizer=optimizer
        )
        validation_metrics = run_epoch(
            model, loaders["validation"], criterion, device=device, optimizer=None
        )
        if epoch > args.warmup_epochs:
            scheduler.step()
        row = {
            "epoch": epoch,
            "train": asdict(train_metrics),
            "validation": asdict(validation_metrics),
        }
        history.append(row)
        print(
            f"epoch={epoch:02d} loss={train_metrics.loss:.4f} "
            f"val_char={validation_metrics.character_accuracy:.4f} "
            f"val_exact={validation_metrics.exact_accuracy:.4f}"
        )
        score = (
            validation_metrics.exact_accuracy,
            validation_metrics.character_accuracy,
            -validation_metrics.loss,
        )
        if score > best:
            best = score
            stale = 0
            torch.save(model.state_dict(), checkpoint)
        else:
            stale += 1
            if stale >= args.patience:
                print(f"early_stop={epoch}")
                break

    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
    test_metrics = run_epoch(model, loaders["test"], criterion, device=device, optimizer=None)
    export_onnx(model, args.output, stack)
    report = {
        "architecture": args.architecture,
        "seed": args.seed,
        "pretrained": not args.no_pretrained,
        "splits": {"train": len(train), "validation": len(validation), "test": len(test)},
        "test": asdict(test_metrics),
        "history": history,
    }
    args.output.with_suffix(".metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"test_char={test_metrics.character_accuracy:.4f} "
        f"test_exact={test_metrics.exact_accuracy:.4f} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from pathlib import Path

import pytest

from scripts.train_captcha_model import CHARSET, Sample, load_samples, split_samples


def make_dataset(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    images = tmp_path / "images"
    images.mkdir()
    lines = ["filename\tlabel"]
    for filename, label in rows:
        (images / filename).write_bytes(b"image")
        lines.append(f"images/{filename}\t{label}")
    (tmp_path / "labels.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_load_samples_accepts_case_sensitive_alphanumeric_labels(tmp_path) -> None:
    dataset = make_dataset(tmp_path, [("one.jpg", "0aAZ"), ("two.jpg", "lI1O")])

    samples = load_samples(dataset)

    assert [sample.label for sample in samples] == ["0aAZ", "lI1O"]
    assert len(CHARSET) == 62


@pytest.mark.parametrize("label", ["abc", "abcde", "ab-1", "áBCD"])
def test_load_samples_rejects_invalid_labels(tmp_path, label) -> None:
    dataset = make_dataset(tmp_path, [("one.jpg", label)])
    with pytest.raises(ValueError, match="Nhãn"):
        load_samples(dataset)


def test_split_keeps_duplicate_labels_together() -> None:
    samples = [
        Sample(Path(f"{label}-{index}.jpg"), label)
        for label in ("AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF")
        for index in range(2)
    ]

    partitions = split_samples(samples, seed=7, validation_ratio=0.2, test_ratio=0.2)
    membership = {
        sample.path: partition
        for partition, rows in enumerate(partitions)
        for sample in rows
    }
    for label in {sample.label for sample in samples}:
        assert len({membership[sample.path] for sample in samples if sample.label == label}) == 1

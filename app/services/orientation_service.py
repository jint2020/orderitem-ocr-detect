from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from PIL import Image, ImageOps


def iter_orientation_images(
    image_path: Path,
    rotations: tuple[int, ...] = (0, 90, 180, 270),
) -> Iterator[tuple[int, Path]]:
    normalized_rotations = _normalize_rotations(rotations)
    if not normalized_rotations:
        return

    with TemporaryDirectory(prefix="unicom-ocr-rot-") as temp_dir:
        temp_root = Path(temp_dir)
        source_image: Image.Image | None = None
        try:
            for rotation in normalized_rotations:
                if source_image is None:
                    with Image.open(image_path) as source:
                        source_image = ImageOps.exif_transpose(source).convert("RGB")

                rotated_path = temp_root / f"{image_path.stem}.rot{rotation}{image_path.suffix}"
                source_image.rotate(rotation, expand=True).save(rotated_path)
                yield rotation, rotated_path
        finally:
            if source_image is not None:
                source_image.close()


def _normalize_rotations(rotations: tuple[int, ...]) -> tuple[int, ...]:
    normalized: list[int] = []
    for rotation in rotations:
        value = rotation % 360
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)

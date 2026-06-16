"""验证图片发现和预处理工具。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from PIL import Image, ImageOps

# 当前验证只处理常见位图格式。PDF、长截图拆分、多页文档都不在第一阶段范围内。
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def discover_images(directory: Path) -> list[Path]:
    """返回目录下支持的图片文件，按路径排序。

    排序是为了让每次验证的处理顺序和输出报告顺序稳定，方便比较多次运行结果。
    """
    if not directory.exists():
        raise FileNotFoundError(f"Image directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Image path is not a directory: {directory}")

    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )


def iter_orientation_images(
    image_path: Path,
    rotations: tuple[int, ...] = (0, 90, 180, 270),
) -> Iterator[tuple[int, Path]]:
    """按候选角度依次产出可供 OCR 读取的图片路径。

    所有候选都会写入临时目录。Pillow 的 `exif_transpose` 会先应用手机照片中的
    EXIF 方向信息，再做显式旋转，避免 PaddleOCR 和 Pillow 对照片方向解释不一致。
    这里返回的是上下文管理器式 generator，调用方必须在同一个循环内完成 OCR。
    """
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
                # Pillow rotate 是逆时针角度；expand=True 保留完整画面。
                source_image.rotate(rotation, expand=True).save(rotated_path)
                yield rotation, rotated_path
        finally:
            if source_image is not None:
                source_image.close()


def _normalize_rotations(rotations: tuple[int, ...]) -> tuple[int, ...]:
    """归一化角度列表，并保持调用方给出的优先顺序。"""
    normalized: list[int] = []
    for rotation in rotations:
        value = rotation % 360
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)

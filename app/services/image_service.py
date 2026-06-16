from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def discover_images(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Image directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Image path is not a directory: {directory}")
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )


def secure_upload_filename(filename: str) -> str:
    secured = secure_filename(filename)
    return secured or "upload.jpg"


def validate_upload_image(file_storage: FileStorage) -> tuple[bool, str]:
    if not file_storage.filename:
        return False, "image is empty"
    if Path(file_storage.filename).suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return False, "unsupported image type"
    position = file_storage.stream.tell()
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(position)
    if size == 0:
        return False, "image is empty"
    return True, ""

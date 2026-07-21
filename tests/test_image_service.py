from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.services.image_service import (
    discover_images,
    secure_upload_filename,
    validate_upload_image,
)


def test_discover_images_returns_supported_files_sorted(tmp_path):
    (tmp_path / "b.jpg").write_bytes(b"fake")
    (tmp_path / "a.png").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_text("ignore")

    assert discover_images(tmp_path) == [tmp_path / "a.png", tmp_path / "b.jpg"]


def test_secure_upload_filename_blocks_path_traversal():
    assert secure_upload_filename("../../x.jpg") == "x.jpg"


def test_validate_upload_image_rejects_unsupported_suffix():
    file_storage = FileStorage(stream=BytesIO(b"abc"), filename="x.txt")

    valid, message = validate_upload_image(file_storage)

    assert valid is False
    assert message == "unsupported image type"

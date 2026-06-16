from io import BytesIO
import json

from werkzeug.datastructures import FileStorage

from app.repositories.ocr_result_repository import OcrResultRepository
from app.services.image_service import discover_images, secure_upload_filename, validate_upload_image


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


def test_repository_writes_workspace_files(tmp_path):
    repository = OcrResultRepository(tmp_path)
    workspace = repository.create_workspace("request-1", "../../sample.jpg")
    file_storage = FileStorage(stream=BytesIO(b"image-bytes"), filename="../../sample.jpg")

    original_path = repository.save_original(workspace, file_storage)
    report_path = repository.save_report(workspace, {"request_id": "request-1"})

    assert original_path == tmp_path / "request-1" / "original" / "sample.jpg"
    assert original_path.read_bytes() == b"image-bytes"
    assert report_path == tmp_path / "request-1" / "report.json"
    assert json.loads(report_path.read_text(encoding="utf-8")) == {"request_id": "request-1"}
    assert workspace.original_key == "requests/request-1/original/sample.jpg"
    assert workspace.label_image_key == "requests/request-1/label_img/sample.jpg"
    assert workspace.report_key == "requests/request-1/report.json"

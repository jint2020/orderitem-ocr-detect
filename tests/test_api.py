from io import BytesIO
from pathlib import Path

from PIL import Image

from app import create_app


class FakeProvider:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[Path] = []

    def predict(self, image_path: Path):
        self.calls.append(image_path)
        if self.fail:
            raise RuntimeError("boom")
        return [
            {
                "res": {
                    "rec_texts": [
                        "号码：",
                        "13800001234复制",
                        "日期：",
                        "2026.06.14 17:18:12",
                        "客户名称：",
                        "张三",
                        "套餐名称：",
                        "5G畅享套餐129元",
                    ],
                    "rec_scores": [0.99, 0.98, 0.99, 0.97, 0.99, 0.96, 0.99, 0.98],
                    "rec_polys": [
                        [[10, 10], [60, 10], [60, 30], [10, 30]],
                        [[200, 10], [360, 10], [360, 30], [200, 30]],
                        [[10, 60], [60, 60], [60, 80], [10, 80]],
                        [[200, 60], [390, 60], [390, 80], [200, 80]],
                        [[10, 110], [100, 110], [100, 130], [10, 130]],
                        [[200, 110], [260, 110], [260, 130], [200, 130]],
                        [[10, 160], [100, 160], [100, 180], [10, 180]],
                        [[200, 160], [430, 160], [430, 180], [200, 180]],
                    ],
                }
            }
        ]


class FailingRepository:
    def create_workspace(self, request_id: str, filename: str):
        raise OSError("disk full")


def _image_bytes() -> BytesIO:
    stream = BytesIO()
    Image.new("RGB", (420, 160), "white").save(stream, format="JPEG")
    stream.seek(0)
    return stream


def _app(tmp_path, provider=None, repository_factory=None, max_content_length=None):
    config = {
        "TESTING": True,
        "OUTPUT_ROOT": tmp_path,
        "OCR_PROVIDER_FACTORY": lambda app: provider or FakeProvider(),
    }
    if repository_factory is not None:
        config["OCR_RESULT_REPOSITORY_FACTORY"] = repository_factory
    if max_content_length is not None:
        config["MAX_CONTENT_LENGTH"] = max_content_length
    return create_app(config)


def test_create_app_registers_openapi_route(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == 0
    assert payload["content"]["openapi"] == "3.0.3"
    assert "/api/v1/ocr/orders" in payload["content"]["paths"]


def test_missing_image_returns_wrapped_400(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.post("/api/v1/ocr/orders", data={})

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "content": {}, "message": "image is required"}


def test_empty_image_returns_wrapped_400(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (BytesIO(b""), "empty.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "content": {}, "message": "image is empty"}


def test_unsupported_suffix_returns_wrapped_400(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (BytesIO(b"abc"), "sample.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "content": {}, "message": "unsupported image type"}


def test_oversized_request_returns_wrapped_413(tmp_path):
    client = _app(tmp_path, max_content_length=10).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (BytesIO(b"a" * 100), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.get_json() == {"code": 413, "content": {}, "message": "image is too large"}


def test_invalid_image_content_returns_wrapped_400(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (BytesIO(b"not an image"), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "content": {}, "message": "invalid image file"}


def test_valid_upload_returns_wrapped_ocr_result(tmp_path):
    provider = FakeProvider()
    client = _app(tmp_path, provider=provider).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "../../sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == 0
    content = payload["content"]
    assert content["fields"]["号码"]["value"] == "13800001234"
    assert set(content["artifacts"]) == {"original_image", "label_image", "report"}
    assert not content["artifacts"]["report"].startswith("/")
    assert (tmp_path / content["request_id"] / "original" / "sample.jpg").exists()
    assert (tmp_path / content["request_id"] / "report.json").exists()


def test_model_config_error_returns_wrapped_500(tmp_path):
    class MissingModelProvider:
        def predict(self, image_path: Path):
            raise FileNotFoundError("missing inference.yml")

    client = _app(tmp_path, provider=MissingModelProvider()).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "ocr model is unavailable"}


def test_provider_exception_returns_wrapped_500(tmp_path):
    client = _app(tmp_path, provider=FakeProvider(fail=True)).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "ocr processing failed"}


def test_repository_write_failure_returns_wrapped_500(tmp_path):
    client = _app(tmp_path, repository_factory=lambda app: FailingRepository()).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "failed to persist ocr result"}

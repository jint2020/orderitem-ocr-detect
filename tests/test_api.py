import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from app import create_app


class FakeProvider:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[Path] = []

    def predict(self, image_path: Path, use_classifier: bool = False):
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


def _image_bytes() -> BytesIO:
    stream = BytesIO()
    Image.new("RGB", (420, 160), "white").save(stream, format="JPEG")
    stream.seek(0)
    return stream


def _app(tmp_path, provider=None, max_content_length=None):
    config = {
        "TESTING": True,
        "OCR_PROVIDER_FACTORY": lambda app: provider or FakeProvider(),
    }
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
    assert content["label_image_base64"]
    image_bytes = base64.b64decode(content["label_image_base64"])
    with Image.open(BytesIO(image_bytes)) as image:
        assert image.size == (420, 160)


def test_label_image_can_be_disabled_via_query_param(tmp_path):
    provider = FakeProvider()
    client = _app(tmp_path, provider=provider).test_client()

    response = client.post(
        "/api/v1/ocr/orders?label_image=false",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    content = response.get_json()["content"]
    assert "label_image_base64" not in content
    assert content["fields"]["号码"]["value"] == "13800001234"


def test_model_config_error_returns_wrapped_500(tmp_path):
    class MissingModelProvider:
        def predict(self, image_path: Path, use_classifier: bool = False):
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


def _auth_app(tmp_path, api_keys):
    return create_app(
        {
            "TESTING": True,
            "OCR_PROVIDER_FACTORY": lambda app: FakeProvider(),
            "API_KEYS": api_keys,
        }
    )


def test_api_key_disabled_by_default_allows_request(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "order.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200


def test_missing_api_key_returns_wrapped_401(tmp_path):
    client = _auth_app(tmp_path, ("secret-key",)).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "order.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 401
    assert response.get_json() == {
        "code": 401,
        "content": {},
        "message": "invalid or missing api key",
    }


def test_wrong_api_key_returns_wrapped_401(tmp_path):
    client = _auth_app(tmp_path, ("secret-key",)).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "order.jpg")},
        content_type="multipart/form-data",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_valid_api_key_allows_request(tmp_path):
    client = _auth_app(tmp_path, ("secret-key",)).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "order.jpg")},
        content_type="multipart/form-data",
        headers={"X-API-Key": "secret-key"},
    )

    assert response.status_code == 200
    assert response.get_json()["code"] == 0


def test_any_configured_api_key_is_accepted(tmp_path):
    client = _auth_app(tmp_path, ("old-key", "new-key")).test_client()

    for key in ("old-key", "new-key"):
        response = client.post(
            "/api/v1/ocr/orders",
            data={"image": (_image_bytes(), "order.jpg")},
            content_type="multipart/form-data",
            headers={"X-API-Key": key},
        )
        assert response.status_code == 200, key


def test_openapi_is_exempt_from_api_key(tmp_path):
    client = _auth_app(tmp_path, ("secret-key",)).test_client()

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert response.get_json()["code"] == 0

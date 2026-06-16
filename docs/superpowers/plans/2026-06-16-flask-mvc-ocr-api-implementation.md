# Flask MVC OCR API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the current OCR CLI validation project into a Flask MVC JSON API under `app/`, with synchronous single-image OCR upload and no supported CLI entrypoint.

**Architecture:** Use Flask application factory, v1 Blueprint controllers, pure OCR/domain services, repository-backed file persistence, hand-written schemas/OpenAPI, and JSON response views. Preserve existing OCR extraction/orientation/quality behavior while changing the boundary from batch CLI to one-upload-one-response API.

**Tech Stack:** Python 3.11/3.12, Flask, pytest, Pillow, PaddleOCR/PaddlePaddle, Hatchling, uv.

---

## File structure map

- Create `app/__init__.py` — Flask `create_app()` and dependency setup.
- Create `app/config.py` — default paths, upload limit, provider/repository factory config keys.
- Create `app/controllers/api/v1/ocr_controller.py` — `/api/v1/ocr/orders` and `/api/v1/openapi.json` routes.
- Create package marker files under `app/controllers/`, `app/controllers/api/`, `app/controllers/api/v1/`, `app/services/`, `app/models/`, `app/repositories/`, `app/schemas/`, `app/views/`.
- Move/adapt `src/unicom_ocr_detect/ocr_result.py` into `app/models/ocr_models.py`.
- Move/adapt `src/unicom_ocr_detect/fields.py` into `app/services/field_extraction.py`.
- Move/adapt `src/unicom_ocr_detect/field_quality.py` into `app/services/field_quality.py`.
- Split `src/unicom_ocr_detect/images.py` into `app/services/image_service.py` and `app/services/orientation_service.py`.
- Move/adapt `src/unicom_ocr_detect/visualization.py` into `app/services/visualization_service.py`.
- Create `app/services/paddle_ocr_provider.py` — lazy PaddleOCR provider and `read_model_name()`.
- Create `app/services/ocr_service.py` — single-upload OCR orchestration.
- Create `app/repositories/ocr_result_repository.py` — file-backed request workspace and report persistence.
- Create `app/schemas/ocr_schema.py` and `app/schemas/response_schema.py` — boundary validation and static OpenAPI dict.
- Create `app/views/json_response.py` — unified `{code, content, message}` responses.
- Replace `tests/test_validation_harness.py` with domain/service tests using `app.*` imports.
- Create `tests/test_api.py` for Flask API behavior.
- Modify `pyproject.toml` — add Flask, remove console script, package `app`.
- Modify `README.md` and `CLAUDE.md` after implementation to remove CLI guidance.
- Remove `src/unicom_ocr_detect/` only after all tests pass against `app.*`.

## Important execution note

Do not create git commits unless the user explicitly asks for commits. The “checkpoint” steps below mean run tests and inspect status; if the user later requests commits, stage the listed files for each checkpoint.

---

### Task 1: Package config and Flask skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/controllers/__init__.py`
- Create: `app/controllers/api/__init__.py`
- Create: `app/controllers/api/v1/__init__.py`
- Create: `app/controllers/api/v1/ocr_controller.py`
- Create: `app/services/__init__.py`
- Create: `app/models/__init__.py`
- Create: `app/repositories/__init__.py`
- Create: `app/schemas/__init__.py`
- Create: `app/views/__init__.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing Flask app tests**

Create `tests/test_api.py`:

```python
from app import create_app


def test_create_app_registers_openapi_route():
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["openapi"] == "3.0.3"
    assert "/api/v1/ocr/orders" in payload["paths"]


def test_missing_image_returns_wrapped_400():
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.post("/api/v1/ocr/orders", data={})

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "content": {}, "message": "image is required"}
```

- [ ] **Step 2: Run tests to verify the Flask app does not exist yet**

Run:

```bash
uv run pytest -q tests/test_api.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or missing `create_app`.

- [ ] **Step 3: Update packaging for Flask and `app` package**

Modify `pyproject.toml` to this content:

```toml
[project]
name = "unicom-ocr-detect"
version = "0.1.0"
description = "OCR JSON API for mobile app order pages."
readme = "README.md"
requires-python = ">=3.11,<3.13"
dependencies = [
    "flask>=3.0.0",
    "paddleocr>=3.3.0",
    "paddlepaddle>=3.2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 4: Create config**

Create `app/config.py`:

```python
from pathlib import Path

DETECTION_MODEL_DIR = Path("models/PP-OCRv6_small_det_infer")
RECOGNITION_MODEL_DIR = Path("models/PP-OCRv6_medium_rec")
OUTPUT_ROOT = Path("outputs/requests")
MAX_CONTENT_LENGTH = 20 * 1024 * 1024
OCR_PROVIDER_FACTORY = None
OCR_RESULT_REPOSITORY_FACTORY = None
```

- [ ] **Step 5: Create package markers**

Create empty files:

```text
app/controllers/__init__.py
app/controllers/api/__init__.py
app/controllers/api/v1/__init__.py
app/services/__init__.py
app/models/__init__.py
app/repositories/__init__.py
app/schemas/__init__.py
app/views/__init__.py
```

- [ ] **Step 6: Create JSON response helpers**

Create `app/views/json_response.py`:

```python
from flask import jsonify


def success(content: dict[str, object], status_code: int = 200):
    return jsonify({"code": 0, "content": content, "message": ""}), status_code


def error(code: int, message: str, status_code: int):
    return jsonify({"code": code, "content": {}, "message": message}), status_code
```

- [ ] **Step 7: Create schema and OpenAPI helpers**

Create `app/schemas/ocr_schema.py`:

```python
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def is_supported_image(filename: str) -> bool:
    return any(filename.lower().endswith(suffix) for suffix in SUPPORTED_IMAGE_SUFFIXES)


def build_openapi_schema() -> dict[str, object]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Unicom OCR API", "version": "1.0.0"},
        "paths": {
            "/api/v1/ocr/orders": {
                "post": {
                    "summary": "Recognize order fields from one uploaded image",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["image"],
                                    "properties": {"image": {"type": "string", "format": "binary"}},
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Wrapped OCR result"},
                        "400": {"description": "Wrapped request error"},
                        "413": {"description": "Wrapped upload size error"},
                        "500": {"description": "Wrapped server error"},
                    },
                }
            }
        },
    }
```

Create `app/schemas/response_schema.py`:

```python
def wrap_success(content: dict[str, object]) -> dict[str, object]:
    return {"code": 0, "content": content, "message": ""}


def wrap_error(code: int, message: str) -> dict[str, object]:
    return {"code": code, "content": {}, "message": message}
```

- [ ] **Step 8: Create initial controller**

Create `app/controllers/api/v1/ocr_controller.py`:

```python
from flask import Blueprint, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.schemas.ocr_schema import build_openapi_schema
from app.views.json_response import error, success

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@api_v1.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_exc):
    return error(413, "image is too large", 413)


@api_v1.get("/openapi.json")
def openapi():
    return success(build_openapi_schema())


@api_v1.post("/ocr/orders")
def recognize_order():
    if "image" not in request.files:
        return error(400, "image is required", 400)
    return success({})
```

- [ ] **Step 9: Create app factory**

Create `app/__init__.py`:

```python
from flask import Flask
from werkzeug.exceptions import RequestEntityTooLarge


def create_app(config_object: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object("app.config")
    if config_object:
        app.config.update(config_object)

    from app.controllers.api.v1.ocr_controller import api_v1

    app.register_blueprint(api_v1)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_exc):
        from app.views.json_response import error

        return error(413, "image is too large", 413)

    return app
```

- [ ] **Step 10: Run skeleton tests**

Run:

```bash
uv sync && uv run pytest -q tests/test_api.py
```

Expected: PASS for the two tests in `tests/test_api.py`.

---

### Task 2: Move OCR domain models and pure rules into `app`

**Files:**
- Create/Modify: `app/models/ocr_models.py`
- Create/Modify: `app/services/field_extraction.py`
- Create/Modify: `app/services/field_quality.py`
- Create/Modify: `app/services/paddle_ocr_provider.py`
- Modify: `tests/test_validation_harness.py`

- [ ] **Step 1: Update domain test imports and filename fallback test**

Modify the imports at the top of `tests/test_validation_harness.py`:

```python
import json
from pathlib import Path

from PIL import Image

from app.services.field_extraction import extract_fields
from app.services.field_quality import apply_quality_to_fields, evaluate_fields
from app.services.image_service import discover_images
from app.models.ocr_models import OcrItem, normalize_paddle_result
from app.services.paddle_ocr_provider import read_model_name
from app.services.ocr_service import OcrService
```

Replace `test_extract_fields_uses_filename_phone_as_fallback_when_ocr_misses_number` with:

```python
def test_extract_fields_uses_filename_phone_as_fallback_when_enabled():
    items = [
        OcrItem(text="日期", score=0.98, box=(10, 60, 60, 80)),
        OcrItem(text="2026年06月14日", score=0.96, box=(200, 60, 400, 80)),
    ]

    fields = extract_fields(
        items,
        image_path=Path("13242337390.jpg"),
        allow_filename_fallback=True,
    )

    assert fields["号码"].value == "13242337390"
    assert fields["号码"].source == "filename"


def test_extract_fields_disables_filename_phone_fallback_by_default():
    items = [
        OcrItem(text="日期", score=0.98, box=(10, 60, 60, 80)),
        OcrItem(text="2026年06月14日", score=0.96, box=(200, 60, 400, 80)),
    ]

    fields = extract_fields(items, image_path=Path("13242337390.jpg"))

    assert fields["号码"].value == ""
    assert fields["号码"].source == "missing"
```

Temporarily leave the three `run_validation` tests failing; they will be converted in Task 5.

- [ ] **Step 2: Run domain tests to verify imports fail**

Run:

```bash
uv run pytest -q tests/test_validation_harness.py::test_normalize_paddle_result_accepts_res_dict_with_polys_and_scores
```

Expected: FAIL until the `app` modules below are created.

- [ ] **Step 3: Create OCR models and result normalization**

Create `app/models/ocr_models.py` by moving the contents of `src/unicom_ocr_detect/ocr_result.py`, then add these imports and dataclasses from existing modules:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OcrItem:
    text: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def center_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.box[3] - self.box[1])

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "score": self.score, "box": [round(value, 2) for value in self.box]}


@dataclass(frozen=True)
class FieldResult:
    value: str
    confidence: float
    box: tuple[float, float, float, float] | None
    source: str
    candidates: tuple[str, ...] = ()

    @property
    def need_confirm(self) -> bool:
        return self.confidence < 0.9

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "box": [round(value, 2) for value in self.box] if self.box else None,
            "source": self.source,
            "candidates": list(self.candidates),
            "need_confirm": self.need_confirm,
        }


@dataclass(frozen=True)
class FieldQuality:
    score: float
    acceptable: bool
    valid_fields: dict[str, bool]
    reasons: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "acceptable": self.acceptable,
            "valid_fields": self.valid_fields,
            "reasons": self.reasons,
        }


def normalize_paddle_result(raw_result: Any) -> list[OcrItem]:
    data = _to_mapping(raw_result)
    res = data.get("res", data)
    texts = res.get("rec_texts") or res.get("dt_texts") or []
    scores = res.get("rec_scores") or res.get("dt_scores") or []
    polys = res.get("rec_polys") or res.get("dt_polys") or res.get("polys") or []

    items: list[OcrItem] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        score = float(scores[index]) if index < len(scores) else 0.0
        poly = polys[index] if index < len(polys) else None
        box = _poly_to_box(poly)
        items.append(OcrItem(text=str(text).strip(), score=score, box=box))
    return items


def _to_mapping(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    if hasattr(raw_result, "json"):
        value = raw_result.json
        if isinstance(value, dict):
            return value
    if hasattr(raw_result, "res"):
        value = raw_result.res
        if isinstance(value, dict):
            return {"res": value}
    if hasattr(raw_result, "__dict__"):
        value = vars(raw_result)
        if isinstance(value, dict):
            return value
    raise TypeError(f"Unsupported PaddleOCR result type: {type(raw_result)!r}")


def _poly_to_box(poly: Any) -> tuple[float, float, float, float]:
    if poly is None:
        return (0.0, 0.0, 0.0, 0.0)
    points = list(poly)
    if len(points) == 4 and all(isinstance(value, (int, float)) for value in points):
        x1, y1, x2, y2 = [float(value) for value in points]
        return (x1, y1, x2, y2)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (min(xs), min(ys), max(xs), max(ys))
```

- [ ] **Step 4: Move field extraction logic**

Create `app/services/field_extraction.py` by copying `src/unicom_ocr_detect/fields.py`, then change imports to:

```python
from app.models.ocr_models import FieldResult, OcrItem
```

Change the function signature and filename fallback condition:

```python
def extract_fields(
    items: list[OcrItem],
    image_path: Path | None = None,
    allow_filename_fallback: bool = False,
) -> dict[str, FieldResult]:
    rows = _group_rows(items)
    results: dict[str, FieldResult] = {}

    for field_name in TARGET_FIELDS:
        result = _extract_inline_label_value(field_name, items)
        if result is None:
            result = _extract_from_rows(field_name, rows)
        if result is None:
            result = _extract_by_pattern(field_name, items)
        if (
            result is None
            and field_name == "号码"
            and image_path is not None
            and allow_filename_fallback
        ):
            result = _extract_phone_from_filename(image_path)
        if result is None:
            result = FieldResult("", 0.0, None, "missing", ())
        results[field_name] = result

    return results
```

Keep the existing constants and private helpers from `fields.py` unchanged.

- [ ] **Step 5: Move field quality logic**

Create `app/services/field_quality.py` by copying `src/unicom_ocr_detect/field_quality.py`, then change imports to:

```python
from app.models.ocr_models import FieldQuality, FieldResult
from app.services.field_extraction import PHONE_RE, TARGET_FIELDS
```

Keep `evaluate_fields()`, `apply_quality_to_fields()`, and private validation helpers unchanged.

- [ ] **Step 6: Create PaddleOCR provider and model-name reader**

Create `app/services/paddle_ocr_provider.py`:

```python
from pathlib import Path
from typing import Any, Protocol

import yaml


class OcrProvider(Protocol):
    def predict(self, image_path: Path) -> list[Any]: ...


class PaddleOcrProvider:
    def __init__(self, det_model_dir: Path, rec_model_dir: Path):
        self.det_model_dir = det_model_dir
        self.rec_model_dir = rec_model_dir
        self._ocr: Any | None = None

    def predict(self, image_path: Path) -> list[Any]:
        return self._get_ocr().predict(str(image_path))

    def _get_ocr(self):
        if self._ocr is None:
            self._ocr = build_paddleocr(self.det_model_dir, self.rec_model_dir)
        return self._ocr


def build_paddleocr(det_model_dir: Path, rec_model_dir: Path):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=read_model_name(det_model_dir),
        text_detection_model_dir=str(det_model_dir),
        text_recognition_model_name=read_model_name(rec_model_dir),
        text_recognition_model_dir=str(rec_model_dir),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
    )


def read_model_name(model_dir: Path) -> str:
    config_path = model_dir / "inference.yml"
    if not config_path.exists():
        raise FileNotFoundError(f"Model config does not exist: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    model_name = config.get("Global", {}).get("model_name")
    if not model_name:
        raise ValueError(f"Global.model_name missing in {config_path}")
    return str(model_name)
```

- [ ] **Step 7: Run focused domain tests**

Run:

```bash
uv run pytest -q \
  tests/test_validation_harness.py::test_normalize_paddle_result_accepts_res_dict_with_polys_and_scores \
  tests/test_validation_harness.py::test_extract_fields_matches_same_row_label_value_pairs \
  tests/test_validation_harness.py::test_extract_fields_uses_filename_phone_as_fallback_when_enabled \
  tests/test_validation_harness.py::test_extract_fields_disables_filename_phone_fallback_by_default \
  tests/test_validation_harness.py::test_field_quality_rejects_invalid_high_confidence_field_values \
  tests/test_validation_harness.py::test_read_model_name_returns_global_model_name_from_inference_yml
```

Expected: PASS.

---

### Task 3: Image, orientation, visualization, and repository services

**Files:**
- Create/Modify: `app/services/image_service.py`
- Create/Modify: `app/services/orientation_service.py`
- Create/Modify: `app/services/visualization_service.py`
- Create/Modify: `app/repositories/ocr_result_repository.py`
- Create: `tests/test_repository_and_image_service.py`

- [ ] **Step 1: Write failing repository/image tests**

Create `tests/test_repository_and_image_service.py`:

```python
from io import BytesIO
import json
from pathlib import Path

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
```

- [ ] **Step 2: Run tests to verify services are missing**

Run:

```bash
uv run pytest -q tests/test_repository_and_image_service.py
```

Expected: FAIL until services are implemented.

- [ ] **Step 3: Implement image service**

Create `app/services/image_service.py`:

```python
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
```

- [ ] **Step 4: Implement orientation service**

Create `app/services/orientation_service.py` by moving `iter_orientation_images()` and `_normalize_rotations()` from `src/unicom_ocr_detect/images.py`, with imports:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from PIL import Image, ImageOps
```

Keep behavior unchanged.

- [ ] **Step 5: Implement visualization service**

Create `app/services/visualization_service.py` by moving `save_label_image()` and helpers from `src/unicom_ocr_detect/visualization.py`, with imports changed to:

```python
from app.models.ocr_models import FieldResult, OcrItem
```

Keep behavior unchanged.

- [ ] **Step 6: Implement repository**

Create `app/repositories/ocr_result_repository.py`:

```python
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage

from app.services.image_service import secure_upload_filename


@dataclass(frozen=True)
class OcrRequestWorkspace:
    request_id: str
    root_dir: Path
    original_dir: Path
    label_image_dir: Path
    report_path: Path
    original_path: Path
    label_image_path: Path
    original_key: str
    label_image_key: str
    report_key: str


class OcrResultRepository:
    def __init__(self, output_root: Path):
        self.output_root = output_root

    def create_workspace(self, request_id: str, filename: str) -> OcrRequestWorkspace:
        safe_name = secure_upload_filename(filename)
        root_dir = self.output_root / request_id
        original_dir = root_dir / "original"
        label_image_dir = root_dir / "label_img"
        original_dir.mkdir(parents=True, exist_ok=True)
        label_image_dir.mkdir(parents=True, exist_ok=True)
        return OcrRequestWorkspace(
            request_id=request_id,
            root_dir=root_dir,
            original_dir=original_dir,
            label_image_dir=label_image_dir,
            report_path=root_dir / "report.json",
            original_path=original_dir / safe_name,
            label_image_path=label_image_dir / safe_name,
            original_key=f"requests/{request_id}/original/{safe_name}",
            label_image_key=f"requests/{request_id}/label_img/{safe_name}",
            report_key=f"requests/{request_id}/report.json",
        )

    def save_original(self, workspace: OcrRequestWorkspace, file_storage: FileStorage) -> Path:
        file_storage.stream.seek(0)
        file_storage.save(workspace.original_path)
        return workspace.original_path

    def save_report(self, workspace: OcrRequestWorkspace, report: dict[str, Any]) -> Path:
        workspace.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return workspace.report_path
```

- [ ] **Step 7: Run repository/image tests**

Run:

```bash
uv run pytest -q tests/test_repository_and_image_service.py
```

Expected: PASS.

---

### Task 4: Single-image OCR service orchestration

**Files:**
- Create/Modify: `app/services/ocr_service.py`
- Modify: `tests/test_validation_harness.py`

- [ ] **Step 1: Replace old run_validation tests with OcrService tests**

Remove `test_run_validation_writes_progress_logs`, `test_run_validation_writes_label_image`, and `test_run_validation_selects_best_rotated_candidate_when_original_quality_is_bad` from `tests/test_validation_harness.py`.

Add:

```python
from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.repositories.ocr_result_repository import OcrResultRepository
```

Add this fake provider if needed:

```python
class AcceptableFirstCandidateFakeOcr:
    def __init__(self):
        self.calls: list[str] = []

    def predict(self, image_path: Path):
        self.calls.append(Path(image_path).name)
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
                        [[200, 110], [260, 110], [260, 80], [200, 130]],
                        [[10, 160], [100, 160], [100, 180], [10, 180]],
                        [[200, 160], [430, 160], [430, 180], [200, 180]],
                    ],
                }
            }
        ]
```

Add service tests:

```python
def _upload_file(name: str = "sample.jpg") -> FileStorage:
    stream = BytesIO()
    Image.new("RGB", (420, 160), "white").save(stream, format="JPEG")
    stream.seek(0)
    return FileStorage(stream=stream, filename=name, content_type="image/jpeg")


def test_ocr_service_writes_report_and_label_image(tmp_path):
    repository = OcrResultRepository(tmp_path)
    service = OcrService(repository=repository, provider=AcceptableFirstCandidateFakeOcr())

    content = service.recognize_order_image(_upload_file(), request_id="request-1")

    assert content["request_id"] == "request-1"
    assert content["fields"]["号码"]["value"] == "13800001234"
    assert content["artifacts"] == {
        "original_image": "requests/request-1/original/sample.jpg",
        "label_image": "requests/request-1/label_img/sample.jpg",
        "report": "requests/request-1/report.json",
    }
    assert (tmp_path / "request-1" / "report.json").exists()
    assert (tmp_path / "request-1" / "label_img" / "sample.jpg").exists()


def test_ocr_service_selects_best_rotated_candidate_when_original_quality_is_bad(tmp_path):
    repository = OcrResultRepository(tmp_path)
    provider = RotationAwareFakeOcr()
    service = OcrService(repository=repository, provider=provider)

    content = service.recognize_order_image(_upload_file(), request_id="request-2")

    assert {name.split(".rot")[1].split(".")[0] for name in provider.calls if ".rot" in name} == {
        "0",
        "90",
        "180",
        "270",
    }
    assert content["selected_rotation_degrees"] == 90
    assert content["field_quality"]["acceptable"] is True
    assert content["fields"]["号码"]["value"] == "18665011878"


def test_ocr_service_stops_after_acceptable_zero_degree_candidate(tmp_path):
    repository = OcrResultRepository(tmp_path)
    provider = AcceptableFirstCandidateFakeOcr()
    service = OcrService(repository=repository, provider=provider)

    service.recognize_order_image(_upload_file(), request_id="request-3")

    assert [name.split(".rot")[1].split(".")[0] for name in provider.calls if ".rot" in name] == ["0"]


def test_ocr_service_disables_filename_phone_fallback_for_api_uploads(tmp_path):
    repository = OcrResultRepository(tmp_path)

    class DateOnlyProvider:
        def predict(self, image_path: Path):
            return [
                {
                    "res": {
                        "rec_texts": ["日期", "2026年06月14日"],
                        "rec_scores": [0.98, 0.96],
                        "rec_polys": [
                            [[10, 60], [60, 60], [60, 80], [10, 80]],
                            [[200, 60], [400, 60], [400, 80], [200, 80]],
                        ],
                    }
                }
            ]

    service = OcrService(repository=repository, provider=DateOnlyProvider())

    content = service.recognize_order_image(_upload_file("13242337390.jpg"), request_id="request-4")

    assert content["fields"]["号码"]["value"] == ""
    assert content["fields"]["号码"]["source"].startswith("missing")
```

- [ ] **Step 2: Run service tests to verify OcrService is missing**

Run:

```bash
uv run pytest -q tests/test_validation_harness.py::test_ocr_service_writes_report_and_label_image
```

Expected: FAIL until `OcrService` is implemented.

- [ ] **Step 3: Implement OcrService**

Create `app/services/ocr_service.py`:

```python
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from werkzeug.datastructures import FileStorage

from app.models.ocr_models import normalize_paddle_result
from app.repositories.ocr_result_repository import OcrResultRepository
from app.services.field_extraction import extract_fields
from app.services.field_quality import apply_quality_to_fields, evaluate_fields
from app.services.orientation_service import iter_orientation_images
from app.services.visualization_service import save_label_image


class OcrProcessingError(RuntimeError):
    pass


class OcrPersistenceError(RuntimeError):
    pass


class OcrService:
    def __init__(self, repository: OcrResultRepository, provider: Any):
        self.repository = repository
        self.provider = provider

    def recognize_order_image(
        self,
        file_storage: FileStorage,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = request_id or str(uuid4())
        workspace = self.repository.create_workspace(request_id, file_storage.filename or "upload.jpg")
        try:
            original_path = self.repository.save_original(workspace, file_storage)
        except OSError as exc:
            raise OcrPersistenceError("failed to persist ocr result") from exc

        started_at = time.time()
        candidate = self._select_orientation_candidate(original_path)
        save_label_image(
            original_path,
            candidate["ocr_items"],
            candidate["fields"],
            workspace.label_image_path,
            rotation_degrees=candidate["rotation_degrees"],
        )
        report = {
            "request_id": request_id,
            "image": str(original_path),
            "elapsed_seconds": round(time.time() - started_at, 4),
            "selected_rotation_degrees": candidate["rotation_degrees"],
            "field_quality": candidate["quality"].to_dict(),
            "orientation_candidates": [
                _candidate_summary(candidate_report)
                for candidate_report in candidate["orientation_candidates"]
            ],
            "artifacts": {
                "original_image": workspace.original_key,
                "label_image": workspace.label_image_key,
                "report": workspace.report_key,
            },
            "label_image": str(workspace.label_image_path),
            "fields": {name: result.to_dict() for name, result in candidate["fields"].items()},
            "raw_ocr": [item.to_dict() for item in candidate["ocr_items"]],
        }
        try:
            self.repository.save_report(workspace, report)
        except OSError as exc:
            raise OcrPersistenceError("failed to persist ocr result") from exc

        return {
            "request_id": request_id,
            "fields": report["fields"],
            "field_quality": report["field_quality"],
            "raw_ocr": report["raw_ocr"],
            "selected_rotation_degrees": report["selected_rotation_degrees"],
            "artifacts": report["artifacts"],
        }

    def _select_orientation_candidate(self, image_path: Path) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        try:
            for rotation, candidate_path in iter_orientation_images(image_path):
                candidate_started_at = time.time()
                raw_results = self.provider.predict(candidate_path)
                ocr_items = []
                for raw_result in raw_results:
                    ocr_items.extend(normalize_paddle_result(raw_result))

                raw_fields = extract_fields(
                    ocr_items,
                    image_path=image_path,
                    allow_filename_fallback=False,
                )
                quality = evaluate_fields(raw_fields)
                fields = apply_quality_to_fields(raw_fields, quality)
                candidate = {
                    "rotation_degrees": rotation,
                    "image_path": candidate_path,
                    "elapsed_seconds": round(time.time() - candidate_started_at, 4),
                    "ocr_items": ocr_items,
                    "fields": fields,
                    "quality": quality,
                }
                candidates.append(candidate)
                if rotation == 0 and quality.acceptable:
                    break
        except Exception as exc:
            raise OcrProcessingError("ocr processing failed") from exc

        return max(
            candidates,
            key=lambda item: (item["quality"].score, -_rotation_cost(item["rotation_degrees"])),
        ) | {"orientation_candidates": candidates}


def _rotation_cost(rotation: int) -> int:
    return min(rotation % 360, (-rotation) % 360)


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "rotation_degrees": candidate["rotation_degrees"],
        "elapsed_seconds": candidate["elapsed_seconds"],
        "ocr_items": len(candidate["ocr_items"]),
        "field_quality": candidate["quality"].to_dict(),
        "fields": {
            name: {
                "value": result.value,
                "confidence": round(result.confidence, 4),
                "source": result.source,
                "need_confirm": result.need_confirm,
            }
            for name, result in candidate["fields"].items()
        },
    }
```

- [ ] **Step 4: Run service tests**

Run:

```bash
uv run pytest -q tests/test_validation_harness.py
```

Expected: all migrated domain/service tests PASS.

---

### Task 5: Complete Flask API controller and error mapping

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/controllers/api/v1/ocr_controller.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Extend API tests**

Replace `tests/test_api.py` with:

```python
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


def _image_bytes() -> BytesIO:
    stream = BytesIO()
    Image.new("RGB", (420, 160), "white").save(stream, format="JPEG")
    stream.seek(0)
    return stream


def _app(tmp_path, provider=None, max_content_length=None):
    config = {
        "TESTING": True,
        "OUTPUT_ROOT": tmp_path,
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


def test_provider_exception_returns_wrapped_500(tmp_path):
    client = _app(tmp_path, provider=FakeProvider(fail=True)).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "ocr processing failed"}
```

- [ ] **Step 2: Run API tests to verify controller is incomplete**

Run:

```bash
uv run pytest -q tests/test_api.py
```

Expected: several tests fail until controller creates repository/service and maps errors.

- [ ] **Step 3: Update app factory dependency setup**

Modify `app/__init__.py`:

```python
from flask import Flask
from werkzeug.exceptions import RequestEntityTooLarge

from app.repositories.ocr_result_repository import OcrResultRepository
from app.services.paddle_ocr_provider import PaddleOcrProvider


def create_app(config_object: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object("app.config")
    if config_object:
        app.config.update(config_object)

    app.extensions["ocr_provider"] = _build_provider(app)
    app.extensions["ocr_repository"] = _build_repository(app)

    from app.controllers.api.v1.ocr_controller import api_v1

    app.register_blueprint(api_v1)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_exc):
        from app.views.json_response import error

        return error(413, "image is too large", 413)

    return app


def _build_provider(app: Flask):
    factory = app.config.get("OCR_PROVIDER_FACTORY")
    if factory is not None:
        return factory(app)
    return PaddleOcrProvider(app.config["DETECTION_MODEL_DIR"], app.config["RECOGNITION_MODEL_DIR"])


def _build_repository(app: Flask):
    factory = app.config.get("OCR_RESULT_REPOSITORY_FACTORY")
    if factory is not None:
        return factory(app)
    return OcrResultRepository(app.config["OUTPUT_ROOT"])
```

- [ ] **Step 4: Update controller to call service**

Modify `app/controllers/api/v1/ocr_controller.py`:

```python
from PIL import UnidentifiedImageError
from flask import Blueprint, current_app, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.schemas.ocr_schema import build_openapi_schema
from app.services.image_service import validate_upload_image
from app.services.ocr_service import OcrPersistenceError, OcrProcessingError, OcrService
from app.views.json_response import error, success

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@api_v1.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_exc):
    return error(413, "image is too large", 413)


@api_v1.get("/openapi.json")
def openapi():
    return success(build_openapi_schema())


@api_v1.post("/ocr/orders")
def recognize_order():
    if "image" not in request.files:
        return error(400, "image is required", 400)

    image = request.files["image"]
    valid, message = validate_upload_image(image)
    if not valid:
        return error(400, message, 400)

    service = OcrService(
        repository=current_app.extensions["ocr_repository"],
        provider=current_app.extensions["ocr_provider"],
    )
    try:
        content = service.recognize_order_image(image)
    except UnidentifiedImageError:
        return error(400, "invalid image file", 400)
    except OcrPersistenceError:
        return error(500, "failed to persist ocr result", 500)
    except OcrProcessingError:
        return error(500, "ocr processing failed", 500)
    except (FileNotFoundError, ValueError):
        return error(500, "ocr model is unavailable", 500)
    return success(content)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
uv run pytest -q tests/test_api.py
```

Expected: PASS.

---

### Task 6: Remove CLI package and update all tests/docs

**Files:**
- Delete: `src/unicom_ocr_detect/`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `doc/ocr流程.md` if continuing to keep local ignored docs current
- Modify: `tests/test_validation_harness.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Run full tests before deletion**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 2: Remove old `src` package**

Run:

```bash
rm -rf src/unicom_ocr_detect
```

Expected: `src/unicom_ocr_detect` is gone. Do not remove unrelated files.

- [ ] **Step 3: Verify no imports reference old package**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in list(Path('app').rglob('*.py')) + list(Path('tests').rglob('*.py')):
    text = path.read_text(encoding='utf-8')
    if 'unicom_ocr_detect' in text or 'ocr-validate' in text:
        print(path)
PY
```

Expected: no output.

- [ ] **Step 4: Update README**

Replace `README.md` with:

```markdown
# unicom-ocr-detect

Flask JSON API for OCR extraction from mobile App order screenshots/photos.

The API accepts one uploaded image, runs local PaddleOCR models, extracts `号码`、`日期`、`姓名`、`套餐信息`, writes request artifacts under `outputs/requests`, and returns a unified JSON response.

## Development

```bash
uv sync
uv run pytest -q
uv run flask --app app run
```

## API

### Recognize one order image

```http
POST /api/v1/ocr/orders
Content-Type: multipart/form-data

image=<single image file>
```

Success response shape:

```json
{
  "code": 0,
  "content": {
    "request_id": "uuid",
    "fields": {},
    "field_quality": {},
    "raw_ocr": [],
    "selected_rotation_degrees": 0,
    "artifacts": {
      "original_image": "requests/<request_id>/original/<filename>",
      "label_image": "requests/<request_id>/label_img/<filename>",
      "report": "requests/<request_id>/report.json"
    }
  },
  "message": ""
}
```

### OpenAPI JSON

```http
GET /api/v1/openapi.json
```

## Defaults

- Text detection: `models/PP-OCRv6_small_det_infer`
- Text recognition: `models/PP-OCRv6_medium_rec`
- Request outputs: `outputs/requests/<request_id>`
- Supported image suffixes: `.jpg`, `.jpeg`, `.png`, `.webp`

## Known caveat

`日期` is currently extracted by prioritizing order-like timestamps over top filter date ranges. It is still marked as `need_confirm=true` until the business definition of `日期` is finalized.
```

- [ ] **Step 5: Update CLAUDE.md commands**

In `CLAUDE.md`, replace CLI commands with:

```markdown
- Install/sync dependencies: `uv sync`
- Run the full test suite: `uv run pytest -q`
- Run a single test file: `uv run pytest -q tests/test_api.py`
- Run the Flask development server: `uv run flask --app app run`
```

Remove references to `uv run ocr-validate` as a supported command.

- [ ] **Step 6: Run full verification**

Run:

```bash
uv sync && uv run pytest -q && uv run python -c 'from app import create_app; app = create_app({"TESTING": True}); print(app.name)'
```

Expected: package sync succeeds, all tests pass, and Python prints `app`.

---

### Task 7: Final manual API smoke check

**Files:**
- No file changes expected unless smoke check reveals a bug.

- [ ] **Step 1: Start Flask app without making a claim of production readiness**

Run in one terminal or background process:

```bash
uv run flask --app app run --port 5001
```

Expected: Flask development server starts.

- [ ] **Step 2: Check OpenAPI endpoint**

Run:

```bash
curl -s http://127.0.0.1:5001/api/v1/openapi.json
```

Expected: JSON response with `code: 0` and `/api/v1/ocr/orders` in `content.paths`.

- [ ] **Step 3: Check missing image endpoint**

Run:

```bash
curl -s -X POST http://127.0.0.1:5001/api/v1/ocr/orders
```

Expected:

```json
{"code":400,"content":{},"message":"image is required"}
```

- [ ] **Step 4: Optional real OCR smoke check**

Run only if local PaddleOCR models are present and loading time is acceptable:

```bash
curl -s -X POST http://127.0.0.1:5001/api/v1/ocr/orders \
  -F image=@data/validation/13242337390.jpg
```

Expected: JSON response with `code: 0`, `content.fields`, and `content.artifacts`. This may take several seconds because OCR is synchronous and may lazily load the model.

- [ ] **Step 5: Stop Flask server**

Stop the dev server process from Step 1.

---

## Self-review notes

- Spec coverage: The plan covers Flask app factory, versioned Blueprint, OpenAPI JSON, single-image synchronous API, unified response wrapper, repository storage, artifact keys, filename fallback policy, provider lifecycle, no CLI, tests, and docs.
- Placeholder scan: This plan intentionally contains no `TBD`, `TODO`, or unspecified implementation slots.
- Type consistency: `OcrRequestWorkspace`, `OcrResultRepository`, `OcrService`, provider `predict(Path)`, and response `artifacts` names are consistent across tasks.

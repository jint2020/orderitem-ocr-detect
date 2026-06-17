# OCR API Follow-up Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the newly refactored Flask MVC OCR JSON API into a more testable, observable, and integration-ready service without changing the accepted single-image synchronous API scope.

**Architecture:** Keep the current Flask MVC boundaries: controllers own HTTP, services own OCR/domain orchestration, repositories own persistence, and schemas/views own API contracts. Improvements should be delivered in priority order and kept behind existing seams so MongoDB, artifact access, and evaluation can evolve without rewriting controllers.

**Tech Stack:** Python 3.11/3.12, Flask, pytest, Pillow, PaddleOCR/PaddlePaddle, Hatchling, uv.

---

## Scope and priority

This is a follow-up improvement backlog, not a request to start implementation immediately. Execute tasks in order unless the user explicitly chooses a different priority.

Priority order:

1. **P0: Contract and regression hardening** — make the current API contract harder to break.
2. **P0: Persistence failure coverage** — verify all repository write stages map to the correct wrapped error.
3. **P1: Artifact read API** — let downstream users fetch stored report/label/original artifacts by key through safe routes.
4. **P1: Ground-truth evaluation harness** — add accuracy-oriented validation using a labels file without reintroducing CLI OCR execution.
5. **P1: Date field semantics** — make `日期` extraction easier to tune once business definition is finalized.
6. **P2: Observability and request timing** — add structured request metadata useful for debugging and future operations.
7. **P2: MongoDB-ready repository contract** — clarify storage interface before adding a real MongoDB implementation.

## File structure map

Expected files to create or modify across the backlog:

- Modify `app/schemas/ocr_schema.py` — expand OpenAPI schema with wrapped response components and artifact routes.
- Modify `tests/test_api.py` — add API contract, artifact route, and mapped error tests.
- Modify `app/controllers/api/v1/ocr_controller.py` — add artifact retrieval endpoints and keep error mapping centralized.
- Modify `app/repositories/ocr_result_repository.py` — add safe artifact lookup methods and strengthen repository exceptions.
- Create `tests/test_artifact_api.py` — focused artifact retrieval tests.
- Create `app/services/evaluation_service.py` — pure comparison logic for expected labels vs OCR fields.
- Create `tests/test_evaluation_service.py` — ground-truth comparison tests.
- Create `data/validation/labels.example.json` — example schema only; do not commit real customer data.
- Modify `app/services/field_extraction.py` — add explicit date extraction helpers once business semantics are known.
- Create or modify `tests/test_date_extraction.py` — date-specific rule tests.
- Modify `app/services/ocr_service.py` — include extra response/report timing fields.
- Modify `README.md` and `CLAUDE.md` — document new endpoints and follow-up validation commands.

## Important execution note

Do not commit unless the user explicitly asks for commits. The commit commands below are checkpoints for a future commit workflow; if commit permission is not granted, run the tests and stop with a summary instead.

---

### Task 1: Harden the OpenAPI and response contract

**Files:**
- Modify: `app/schemas/ocr_schema.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add an API contract test for response wrapper schema**

Append to `tests/test_api.py`:

```python
def test_openapi_declares_wrapped_success_and_error_responses(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.get_json()["content"]
    components = schema["components"]["schemas"]
    assert components["WrappedSuccess"]["required"] == ["code", "content", "message"]
    assert components["WrappedError"]["properties"]["content"]["additionalProperties"] is False
    responses = schema["paths"]["/api/v1/ocr/orders"]["post"]["responses"]
    assert responses["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/WrappedOcrResult"
    assert responses["400"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/WrappedError"
```

- [ ] **Step 2: Run the failing contract test**

Run:

```bash
uv run pytest -q tests/test_api.py::test_openapi_declares_wrapped_success_and_error_responses
```

Expected: FAIL with `KeyError: 'components'` or missing response content schema.

- [ ] **Step 3: Expand OpenAPI schema components**

Replace `build_openapi_schema()` in `app/schemas/ocr_schema.py` with:

```python
def build_openapi_schema() -> dict[str, object]:
    wrapped_error = {"$ref": "#/components/schemas/WrappedError"}
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
                        "200": _json_response_schema({"$ref": "#/components/schemas/WrappedOcrResult"}),
                        "400": _json_response_schema(wrapped_error),
                        "413": _json_response_schema(wrapped_error),
                        "500": _json_response_schema(wrapped_error),
                    },
                }
            },
            "/api/v1/openapi.json": {
                "get": {
                    "summary": "Return the OpenAPI schema wrapped in the standard response envelope",
                    "responses": {"200": _json_response_schema({"$ref": "#/components/schemas/WrappedSuccess"})},
                }
            },
        },
        "components": {
            "schemas": {
                "WrappedSuccess": _wrapped_success_schema({"type": "object"}),
                "WrappedOcrResult": _wrapped_success_schema({"$ref": "#/components/schemas/OcrResult"}),
                "WrappedError": {
                    "type": "object",
                    "required": ["code", "content", "message"],
                    "properties": {
                        "code": {"type": "integer", "example": 400},
                        "content": {"type": "object", "additionalProperties": False},
                        "message": {"type": "string", "example": "image is required"},
                    },
                },
                "OcrResult": {
                    "type": "object",
                    "required": [
                        "request_id",
                        "fields",
                        "field_quality",
                        "raw_ocr",
                        "selected_rotation_degrees",
                        "artifacts",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "fields": {"type": "object"},
                        "field_quality": {"type": "object"},
                        "raw_ocr": {"type": "array", "items": {"type": "object"}},
                        "selected_rotation_degrees": {"type": "integer", "enum": [0, 90, 180, 270]},
                        "artifacts": {
                            "type": "object",
                            "required": ["original_image", "label_image", "report"],
                            "properties": {
                                "original_image": {"type": "string"},
                                "label_image": {"type": "string"},
                                "report": {"type": "string"},
                            },
                        },
                    },
                },
            }
        },
    }


def _json_response_schema(schema: dict[str, object]) -> dict[str, object]:
    return {
        "description": "Wrapped JSON response",
        "content": {"application/json": {"schema": schema}},
    }


def _wrapped_success_schema(content_schema: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "required": ["code", "content", "message"],
        "properties": {
            "code": {"type": "integer", "enum": [0]},
            "content": content_schema,
            "message": {"type": "string", "enum": [""]},
        },
    }
```

Keep `SUPPORTED_IMAGE_SUFFIXES` and `is_supported_image()` unchanged.

- [ ] **Step 4: Run API tests**

Run:

```bash
uv run pytest -q tests/test_api.py
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If commits are authorized:

```bash
git add app/schemas/ocr_schema.py tests/test_api.py
git commit -m "test: harden OCR API contract schema"
```

Expected: new commit records OpenAPI contract hardening.

---

### Task 2: Cover every persistence failure stage

**Files:**
- Modify: `tests/test_api.py`
- Modify: `app/services/ocr_service.py`

- [ ] **Step 1: Add tests for original, label, and report write failures**

Append to `tests/test_api.py`:

```python
class StageFailingRepository:
    def __init__(self, output_root, fail_stage: str):
        from app.repositories.ocr_result_repository import OcrResultRepository

        self.inner = OcrResultRepository(output_root)
        self.fail_stage = fail_stage

    def create_workspace(self, request_id: str, filename: str):
        if self.fail_stage == "create_workspace":
            raise OSError("cannot create workspace")
        return self.inner.create_workspace(request_id, filename)

    def save_original(self, workspace, file_storage):
        if self.fail_stage == "save_original":
            raise OSError("cannot save original")
        return self.inner.save_original(workspace, file_storage)

    def save_report(self, workspace, report):
        if self.fail_stage == "save_report":
            raise OSError("cannot save report")
        return self.inner.save_report(workspace, report)


def test_workspace_creation_failure_returns_wrapped_500(tmp_path):
    client = _app(
        tmp_path,
        repository_factory=lambda app: StageFailingRepository(tmp_path, "create_workspace"),
    ).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "failed to persist ocr result"}


def test_original_save_failure_returns_wrapped_500(tmp_path):
    client = _app(
        tmp_path,
        repository_factory=lambda app: StageFailingRepository(tmp_path, "save_original"),
    ).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "failed to persist ocr result"}


def test_report_save_failure_returns_wrapped_500(tmp_path):
    client = _app(
        tmp_path,
        repository_factory=lambda app: StageFailingRepository(tmp_path, "save_report"),
    ).test_client()

    response = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "content": {}, "message": "failed to persist ocr result"}
```

- [ ] **Step 2: Run the new persistence tests**

Run:

```bash
uv run pytest -q \
  tests/test_api.py::test_workspace_creation_failure_returns_wrapped_500 \
  tests/test_api.py::test_original_save_failure_returns_wrapped_500 \
  tests/test_api.py::test_report_save_failure_returns_wrapped_500
```

Expected: PASS if current `OcrService` already wraps these stages; otherwise FAIL where the service leaks an `OSError`.

- [ ] **Step 3: Patch service only if a stage leaks**

If Step 2 fails, replace the beginning and report write portions of `OcrService.recognize_order_image()` in `app/services/ocr_service.py` with this exact structure:

```python
        request_id = request_id or str(uuid4())
        try:
            workspace = self.repository.create_workspace(request_id, file_storage.filename or "upload.jpg")
            original_path = self.repository.save_original(workspace, file_storage)
        except OSError as exc:
            raise OcrPersistenceError("failed to persist ocr result") from exc

        started_at = time.time()
        candidate = self._select_orientation_candidate(original_path)
        try:
            save_label_image(
                original_path,
                candidate["ocr_items"],
                candidate["fields"],
                workspace.label_image_path,
                rotation_degrees=candidate["rotation_degrees"],
            )
        except OSError as exc:
            raise OcrPersistenceError("failed to persist ocr result") from exc
```

and keep the existing report write wrapper:

```python
        try:
            self.repository.save_report(workspace, report)
        except OSError as exc:
            raise OcrPersistenceError("failed to persist ocr result") from exc
```

- [ ] **Step 4: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If commits are authorized:

```bash
git add app/services/ocr_service.py tests/test_api.py
git commit -m "test: cover OCR persistence failure mapping"
```

Expected: new commit records persistence error coverage.

---

### Task 3: Add safe artifact retrieval API

**Files:**
- Modify: `app/repositories/ocr_result_repository.py`
- Modify: `app/controllers/api/v1/ocr_controller.py`
- Modify: `app/schemas/ocr_schema.py`
- Create: `tests/test_artifact_api.py`
- Modify: `README.md`

- [ ] **Step 1: Write artifact API tests**

Create `tests/test_artifact_api.py`:

```python
from io import BytesIO
from pathlib import Path

from PIL import Image

from app import create_app


class FakeProvider:
    def predict(self, image_path: Path):
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


def _client(tmp_path):
    app = create_app({"TESTING": True, "OUTPUT_ROOT": tmp_path, "OCR_PROVIDER_FACTORY": lambda app: FakeProvider()})
    return app.test_client()


def test_get_report_artifact_returns_saved_report(tmp_path):
    client = _client(tmp_path)
    upload = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )
    request_id = upload.get_json()["content"]["request_id"]

    response = client.get(f"/api/v1/ocr/orders/{request_id}/artifacts/report")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["request_id"] == request_id
    assert payload["fields"]["号码"]["value"] == "13800001234"


def test_get_label_artifact_returns_image(tmp_path):
    client = _client(tmp_path)
    upload = client.post(
        "/api/v1/ocr/orders",
        data={"image": (_image_bytes(), "sample.jpg")},
        content_type="multipart/form-data",
    )
    request_id = upload.get_json()["content"]["request_id"]

    response = client.get(f"/api/v1/ocr/orders/{request_id}/artifacts/label_image")

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.data.startswith(b"\xff\xd8")


def test_get_missing_artifact_returns_wrapped_404(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/v1/ocr/orders/missing-request/artifacts/report")

    assert response.status_code == 404
    assert response.get_json() == {"code": 404, "content": {}, "message": "artifact not found"}


def test_get_artifact_rejects_unknown_kind(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/v1/ocr/orders/request-1/artifacts/../../secret")

    assert response.status_code in {404, 400}
```

- [ ] **Step 2: Run failing artifact tests**

Run:

```bash
uv run pytest -q tests/test_artifact_api.py
```

Expected: FAIL with 404 route not found or missing repository method.

- [ ] **Step 3: Add repository artifact lookup**

Append to `app/repositories/ocr_result_repository.py`:

```python
    def artifact_path(self, request_id: str, artifact_kind: str) -> Path | None:
        root_dir = self.output_root / request_id
        candidates = {
            "report": root_dir / "report.json",
            "original_image": self._single_file(root_dir / "original"),
            "label_image": self._single_file(root_dir / "label_img"),
        }
        path = candidates.get(artifact_kind)
        if path is None or not path.exists() or not path.is_file():
            return None
        if not path.resolve().is_relative_to(root_dir.resolve()):
            return None
        return path

    def _single_file(self, directory: Path) -> Path | None:
        if not directory.exists() or not directory.is_dir():
            return None
        files = sorted(path for path in directory.iterdir() if path.is_file())
        return files[0] if files else None
```

- [ ] **Step 4: Add artifact controller route**

Append to `app/controllers/api/v1/ocr_controller.py`:

```python
from flask import send_file
```

Then add this route below `recognize_order()`:

```python
@api_v1.get("/ocr/orders/<request_id>/artifacts/<artifact_kind>")
def get_artifact(request_id: str, artifact_kind: str):
    if artifact_kind not in {"report", "original_image", "label_image"}:
        return error(400, "unsupported artifact type", 400)

    path = current_app.extensions["ocr_repository"].artifact_path(request_id, artifact_kind)
    if path is None:
        return error(404, "artifact not found", 404)

    if artifact_kind == "report":
        return send_file(path, mimetype="application/json")
    return send_file(path)
```

- [ ] **Step 5: Add artifact route to OpenAPI**

In `app/schemas/ocr_schema.py`, add a path entry for:

```python
            "/api/v1/ocr/orders/{request_id}/artifacts/{artifact_kind}": {
                "get": {
                    "summary": "Fetch a persisted OCR artifact",
                    "parameters": [
                        {"name": "request_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {
                            "name": "artifact_kind",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "enum": ["report", "original_image", "label_image"]},
                        },
                    ],
                    "responses": {
                        "200": {"description": "Artifact bytes"},
                        "400": _json_response_schema(wrapped_error),
                        "404": _json_response_schema(wrapped_error),
                    },
                }
            },
```

- [ ] **Step 6: Document artifact retrieval**

Add to `README.md` under API:

```markdown
### Fetch a stored artifact

```http
GET /api/v1/ocr/orders/<request_id>/artifacts/report
GET /api/v1/ocr/orders/<request_id>/artifacts/original_image
GET /api/v1/ocr/orders/<request_id>/artifacts/label_image
```

The report returns JSON. Image artifacts return image bytes. Unknown or missing artifacts return the standard wrapped error response.
```

- [ ] **Step 7: Run artifact and API tests**

Run:

```bash
uv run pytest -q tests/test_artifact_api.py tests/test_api.py
```

Expected: PASS.

- [ ] **Step 8: Checkpoint**

If commits are authorized:

```bash
git add app/controllers/api/v1/ocr_controller.py app/repositories/ocr_result_repository.py app/schemas/ocr_schema.py tests/test_artifact_api.py README.md
git commit -m "feat: add safe OCR artifact retrieval API"
```

Expected: new commit records artifact retrieval.

---

### Task 4: Add pure ground-truth evaluation service

**Files:**
- Create: `app/services/evaluation_service.py`
- Create: `tests/test_evaluation_service.py`
- Create: `data/validation/labels.example.json`
- Modify: `README.md`

- [ ] **Step 1: Write evaluation tests**

Create `tests/test_evaluation_service.py`:

```python
from app.services.evaluation_service import evaluate_report_against_labels


def test_evaluate_report_against_labels_counts_field_matches():
    report = {
        "fields": {
            "号码": {"value": "13800001234"},
            "日期": {"value": "2026.06.14 17:18:12"},
            "姓名": {"value": "张三"},
            "套餐信息": {"value": "5G畅享套餐129元"},
        }
    }
    expected = {
        "号码": "13800001234",
        "日期": "2026.06.14 17:18:12",
        "姓名": "李四",
        "套餐信息": "5G畅享套餐129元",
    }

    result = evaluate_report_against_labels(report, expected)

    assert result == {
        "field_total": 4,
        "field_correct": 3,
        "all_correct": False,
        "fields": {
            "号码": {"expected": "13800001234", "actual": "13800001234", "correct": True},
            "日期": {"expected": "2026.06.14 17:18:12", "actual": "2026.06.14 17:18:12", "correct": True},
            "姓名": {"expected": "李四", "actual": "张三", "correct": False},
            "套餐信息": {"expected": "5G畅享套餐129元", "actual": "5G畅享套餐129元", "correct": True},
        },
    }


def test_evaluate_report_treats_missing_actual_as_incorrect():
    report = {"fields": {"号码": {"value": ""}}}
    expected = {"号码": "13800001234"}

    result = evaluate_report_against_labels(report, expected)

    assert result["field_total"] == 1
    assert result["field_correct"] == 0
    assert result["fields"]["号码"] == {"expected": "13800001234", "actual": "", "correct": False}
```

- [ ] **Step 2: Run failing evaluation tests**

Run:

```bash
uv run pytest -q tests/test_evaluation_service.py
```

Expected: FAIL with missing `app.services.evaluation_service`.

- [ ] **Step 3: Implement evaluation service**

Create `app/services/evaluation_service.py`:

```python
def evaluate_report_against_labels(
    report: dict[str, object],
    expected_fields: dict[str, str],
) -> dict[str, object]:
    actual_fields = report.get("fields", {})
    field_results: dict[str, dict[str, object]] = {}
    correct_count = 0

    for field_name, expected_value in expected_fields.items():
        actual_value = _field_value(actual_fields, field_name)
        correct = actual_value == expected_value
        if correct:
            correct_count += 1
        field_results[field_name] = {
            "expected": expected_value,
            "actual": actual_value,
            "correct": correct,
        }

    total = len(expected_fields)
    return {
        "field_total": total,
        "field_correct": correct_count,
        "all_correct": total > 0 and correct_count == total,
        "fields": field_results,
    }


def _field_value(actual_fields: object, field_name: str) -> str:
    if not isinstance(actual_fields, dict):
        return ""
    field = actual_fields.get(field_name, {})
    if not isinstance(field, dict):
        return ""
    value = field.get("value", "")
    return str(value).strip()
```

- [ ] **Step 4: Add labels example**

Create `data/validation/labels.example.json`:

```json
{
  "example.jpg": {
    "号码": "13800001234",
    "日期": "2026.06.14 17:18:12",
    "姓名": "张三",
    "套餐信息": "5G畅享套餐129元"
  }
}
```

- [ ] **Step 5: Document evaluation service scope**

Add to `README.md` under Known caveat or Documentation:

```markdown
## Evaluation helper

`app.services.evaluation_service.evaluate_report_against_labels(report, expected_fields)` compares one saved OCR report against expected field values. It does not run OCR and does not reintroduce the old CLI; callers can use it from tests, notebooks, or a future admin-only evaluation endpoint.
```

- [ ] **Step 6: Run evaluation and full tests**

Run:

```bash
uv run pytest -q tests/test_evaluation_service.py && uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Checkpoint**

If commits are authorized:

```bash
git add app/services/evaluation_service.py tests/test_evaluation_service.py data/validation/labels.example.json README.md
git commit -m "feat: add OCR ground truth evaluation helper"
```

Expected: new commit records evaluation helper.

---

### Task 5: Prepare date extraction for finalized business semantics

**Files:**
- Modify: `app/services/field_extraction.py`
- Create: `tests/test_date_extraction.py`
- Modify: `README.md`

- [ ] **Step 1: Write date semantics tests**

Create `tests/test_date_extraction.py`:

```python
from app.models.ocr_models import OcrItem
from app.services.field_extraction import extract_fields


def test_date_prefers_labeled_order_time_over_top_filter_range():
    items = [
        OcrItem(text="2026.06.01-2026.06.16", score=0.99, box=(10, 10, 260, 30)),
        OcrItem(text="办理时间：", score=0.99, box=(10, 100, 100, 120)),
        OcrItem(text="2026.06.14 17:18:12", score=0.98, box=(200, 100, 390, 120)),
    ]

    fields = extract_fields(items)

    assert fields["日期"].value == "2026.06.14 17:18:12"
    assert fields["日期"].source == "label_value"


def test_date_does_not_use_filter_range_when_order_timestamp_exists():
    items = [
        OcrItem(text="2026.06.01-2026.06.16", score=0.99, box=(10, 10, 260, 30)),
        OcrItem(text="2026.06.14 17:18:12", score=0.98, box=(10, 100, 260, 120)),
    ]

    fields = extract_fields(items)

    assert fields["日期"].value == "2026.06.14 17:18:12"
    assert fields["日期"].source == "timestamp_pattern"
```

- [ ] **Step 2: Run date tests**

Run:

```bash
uv run pytest -q tests/test_date_extraction.py
```

Expected: PASS if current extraction already satisfies this behavior; otherwise FAIL with the wrong date value/source.

- [ ] **Step 3: Refactor date pattern helper only if tests fail**

If Step 2 fails because date range is selected over order timestamp, modify `_extract_by_pattern()` in `app/services/field_extraction.py` so the `日期` branch is:

```python
    if field_name == "日期":
        match = TIMESTAMP_RE.search(joined)
        if match:
            value = _normalize_timestamp(match.group(0))
            return FieldResult(value, 0.85, None, "timestamp_pattern", (value,))
        match = DATE_RE.search(joined)
        if match:
            return FieldResult(match.group(0), 0.75, None, "pattern", (match.group(0),))
```

Do not add new date sources until the business definition is finalized.

- [ ] **Step 4: Document current date policy**

Add to `README.md` Known caveat:

```markdown
Current date policy: explicit label-value dates are preferred when present; otherwise timestamp-like order dates are preferred over top filter date ranges. This remains a heuristic until the business definition of `日期` is finalized.
```

- [ ] **Step 5: Run date and domain tests**

Run:

```bash
uv run pytest -q tests/test_date_extraction.py tests/test_validation_harness.py
```

Expected: PASS.

- [ ] **Step 6: Checkpoint**

If commits are authorized:

```bash
git add app/services/field_extraction.py tests/test_date_extraction.py README.md
git commit -m "test: pin OCR date extraction policy"
```

Expected: new commit records date policy tests.

---

### Task 6: Add lightweight request timing metadata

**Files:**
- Modify: `app/services/ocr_service.py`
- Modify: `tests/test_validation_harness.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add service-level timing assertions**

Append to `tests/test_validation_harness.py`:

```python
def test_ocr_service_response_includes_timing_metadata(tmp_path):
    repository = OcrResultRepository(tmp_path)
    service = OcrService(repository=repository, provider=AcceptableFirstCandidateFakeOcr())

    content = service.recognize_order_image(_upload_file(), request_id="request-timing")

    assert set(content["timing"]) == {"elapsed_seconds"}
    assert isinstance(content["timing"]["elapsed_seconds"], float)
    assert content["timing"]["elapsed_seconds"] >= 0.0
```

- [ ] **Step 2: Add API timing assertion**

In `tests/test_api.py`, add to `test_valid_upload_returns_wrapped_ocr_result()` after `content = payload["content"]`:

```python
    assert set(content["timing"]) == {"elapsed_seconds"}
    assert content["timing"]["elapsed_seconds"] >= 0.0
```

- [ ] **Step 3: Run failing timing tests**

Run:

```bash
uv run pytest -q \
  tests/test_validation_harness.py::test_ocr_service_response_includes_timing_metadata \
  tests/test_api.py::test_valid_upload_returns_wrapped_ocr_result
```

Expected: FAIL with `KeyError: 'timing'`.

- [ ] **Step 4: Add timing to service response**

In `app/services/ocr_service.py`, add `timing` to the returned content dict:

```python
        return {
            "request_id": request_id,
            "fields": report["fields"],
            "field_quality": report["field_quality"],
            "raw_ocr": report["raw_ocr"],
            "selected_rotation_degrees": report["selected_rotation_degrees"],
            "artifacts": report["artifacts"],
            "timing": {"elapsed_seconds": report["elapsed_seconds"]},
        }
```

- [ ] **Step 5: Update OpenAPI OcrResult schema**

In `app/schemas/ocr_schema.py`, add `timing` to the `OcrResult` required list and properties:

```python
                        "timing": {
                            "type": "object",
                            "required": ["elapsed_seconds"],
                            "properties": {"elapsed_seconds": {"type": "number"}},
                        },
```

- [ ] **Step 6: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Checkpoint**

If commits are authorized:

```bash
git add app/services/ocr_service.py app/schemas/ocr_schema.py tests/test_validation_harness.py tests/test_api.py
git commit -m "feat: expose OCR request timing metadata"
```

Expected: new commit records timing metadata.

---

### Task 7: Clarify repository contract before MongoDB

**Files:**
- Modify: `app/repositories/ocr_result_repository.py`
- Create: `tests/test_repository_contract.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write contract tests for repository return shape**

Create `tests/test_repository_contract.py`:

```python
from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.repositories.ocr_result_repository import OcrResultRepository


def test_repository_workspace_exposes_stable_storage_keys(tmp_path):
    repository = OcrResultRepository(tmp_path)

    workspace = repository.create_workspace("request-1", "../../sample.jpg")

    assert workspace.original_key == "requests/request-1/original/sample.jpg"
    assert workspace.label_image_key == "requests/request-1/label_img/sample.jpg"
    assert workspace.report_key == "requests/request-1/report.json"
    assert not workspace.original_key.startswith("/")
    assert not workspace.label_image_key.startswith("/")
    assert not workspace.report_key.startswith("/")


def test_repository_save_report_returns_report_path(tmp_path):
    repository = OcrResultRepository(tmp_path)
    workspace = repository.create_workspace("request-1", "sample.jpg")

    path = repository.save_report(workspace, {"ok": True})

    assert path == tmp_path / "request-1" / "report.json"
    assert path.exists()


def test_repository_save_original_rewinds_stream(tmp_path):
    repository = OcrResultRepository(tmp_path)
    workspace = repository.create_workspace("request-1", "sample.jpg")
    stream = BytesIO(b"abcdef")
    stream.seek(3)
    file_storage = FileStorage(stream=stream, filename="sample.jpg")

    path = repository.save_original(workspace, file_storage)

    assert path.read_bytes() == b"abcdef"
```

- [ ] **Step 2: Run repository contract tests**

Run:

```bash
uv run pytest -q tests/test_repository_contract.py
```

Expected: PASS with current repository behavior. If it fails, fix only the repository method needed by the failing assertion.

- [ ] **Step 3: Add repository interface note**

Add this docstring to `OcrResultRepository` in `app/repositories/ocr_result_repository.py`:

```python
class OcrResultRepository:
    """File-backed storage boundary for OCR request artifacts.

    Controllers and services consume storage keys, not absolute paths, so a future
    MongoDB or object-storage repository can preserve the API response shape.
    """
```

- [ ] **Step 4: Update CLAUDE.md repository guidance**

Add under architecture in `CLAUDE.md`:

```markdown
When changing persistence, keep controllers dependent on `OcrResultRepository` behavior rather than filesystem layout. API responses should continue to expose artifact keys, not absolute paths, so MongoDB/object-storage migration does not change clients.
```

- [ ] **Step 5: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Checkpoint**

If commits are authorized:

```bash
git add app/repositories/ocr_result_repository.py tests/test_repository_contract.py CLAUDE.md
git commit -m "test: lock OCR repository storage contract"
```

Expected: new commit records repository contract tests.

---

## Final verification for any implemented subset

After implementing any selected tasks, always run:

```bash
uv sync && uv run pytest -q && uv run python -c 'from app import create_app; app = create_app({"TESTING": True}); print(app.name)'
```

Expected:

```text
30+ passed
app
```

The exact test count will increase as improvement tasks are implemented.

## Self-review notes

- Spec coverage: The plan covers API contract hardening, storage failure coverage, artifact access, ground-truth evaluation, date semantics, timing observability, and MongoDB-ready repository boundaries.
- Scope check: These are independent follow-up improvements. Execute them task-by-task; artifact API, evaluation, date policy, timing, and repository contract can each ship separately.
- Placeholder scan: The plan contains no `TBD`, `TODO`, or unspecified implementation slots.
- Type consistency: Names used across tests and implementation steps match current code: `OcrService`, `OcrResultRepository`, `artifact_path`, `evaluate_report_against_labels`, `build_openapi_schema`, `timing.elapsed_seconds`.

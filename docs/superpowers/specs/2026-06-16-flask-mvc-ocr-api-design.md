# Flask MVC OCR API Design

## Goal

Refactor the current OCR validation CLI into a Flask-based MVC JSON API project under the `app/` package. The new project will no longer expose or support CLI invocation; OCR is triggered through a synchronous single-image upload API.

## Approved scope

- Use Flask.
- Use Blueprint-based API versioning.
- Expose JSON API only; no HTML pages.
- Provide OpenAPI JSON; no Swagger UI in the first version.
- Accept one uploaded image per request.
- Run OCR synchronously and return the result in the HTTP response.
- Wrap every response as `{code, content, message}`.
- Persist uploaded image, per-request report JSON, and label image under `outputs/requests/<request_id>/`.
- Keep storage behind a repository boundary so future MongoDB persistence can be added without changing controllers.
- Return storage artifact keys in API responses; local filesystem paths may appear only as debug metadata in reports.
- Disable filename-based phone fallback for API requests by default because uploaded filenames are not trustworthy.
- Remove CLI invocation support, including the `ocr-validate` console script.

Out of scope for this refactor:

- HTML UI.
- Batch upload.
- Async job queue.
- MongoDB implementation.
- Swagger UI.
- Production authentication or permissions.

## Architecture

The target architecture is Flask Application Factory plus MVC-style layering:

```text
app/
  __init__.py
  config.py

  controllers/
    __init__.py
    api/
      __init__.py
      v1/
        __init__.py
        ocr_controller.py

  services/
    __init__.py
    ocr_service.py
    paddle_ocr_provider.py
    image_service.py
    orientation_service.py
    field_extraction.py
    field_quality.py
    visualization_service.py

  models/
    __init__.py
    ocr_models.py

  repositories/
    __init__.py
    ocr_result_repository.py

  schemas/
    __init__.py
    ocr_schema.py
    response_schema.py

  views/
    __init__.py
    json_response.py
```

The existing OCR domain code currently under `src/unicom_ocr_detect/` will move into `app/`. The refactor should preserve the current OCR behavior while changing the application boundary from CLI batch validation to a web API request lifecycle.

Layer placement for current modules:

- `ocr_result.py` dataclasses and normalization move to `app/models/ocr_models.py` and pure helpers in `app/services/ocr_result_normalizer.py` if the file grows too large.
- `fields.py` moves to `app/services/field_extraction.py`; it remains pure domain logic with no Flask imports.
- `field_quality.py` moves to `app/services/field_quality.py`; it remains pure domain logic with no Flask imports.
- `images.py` splits into upload boundary helpers in `app/services/image_service.py` and OCR orientation helpers in `app/services/orientation_service.py`.
- `visualization.py` moves to `app/services/visualization_service.py`; it writes label images only through paths provided by the repository.
- `run_validation.py` is not migrated as a callable CLI module. Its orchestration logic is re-expressed in `app/services/ocr_service.py` for a single uploaded image.

## Module responsibilities

### Application factory

`app/__init__.py` exposes `create_app(config_object=None)`. It creates the Flask app, loads default config from `app.config`, applies test overrides, and registers the API v1 blueprint.

### Config

`app/config.py` owns runtime settings:

```python
from pathlib import Path

DETECTION_MODEL_DIR = Path("models/PP-OCRv6_small_det_infer")
RECOGNITION_MODEL_DIR = Path("models/PP-OCRv6_medium_rec")
OUTPUT_ROOT = Path("outputs/requests")
MAX_CONTENT_LENGTH = 20 * 1024 * 1024
```

Tests can override model paths, output root, and OCR provider construction to avoid loading real PaddleOCR.

The app factory should accept dependency overrides through config, including `OCR_PROVIDER_FACTORY` and `OCR_RESULT_REPOSITORY_FACTORY`. In production defaults, the provider is created lazily and reused for subsequent requests within the same Flask process. This avoids loading PaddleOCR models on every request. Flask's debug reloader may create more than one process, so repeated model loading in debug mode is acceptable but should not happen per request in a single process.

### Controllers

`app/controllers/api/v1/ocr_controller.py` owns HTTP concerns only:

- Register `POST /api/v1/ocr/orders`.
- Register `GET /api/v1/openapi.json`.
- Read `multipart/form-data`.
- Ensure the `image` field exists.
- Delegate request validation to schema helpers.
- Call `OcrService`.
- Return wrapped JSON responses via the view layer.

Controllers must not contain OCR rules, PaddleOCR calls, report writing, or filesystem layout logic.

### Services

`app/services/ocr_service.py` orchestrates the OCR use case for one uploaded image:

1. Generate a `request_id`.
2. Ask the repository for a per-request output directory.
3. Save the uploaded image through `image_service.py`.
4. Run orientation candidate OCR using the provider.
5. Normalize OCR output into internal model objects.
6. Extract `号码`、`日期`、`姓名`、`套餐信息`.
7. Evaluate field quality and lower confidence for rejected fields.
8. Save the label image.
9. Build the report dictionary.
10. Persist the report through the repository.
11. Return the response content dictionary.

`app/services/paddle_ocr_provider.py` isolates PaddleOCR initialization and `predict()` calls. It reads model names from local `inference.yml` files just like the current implementation. The provider contract is:

```python
class OcrProvider:
    def predict(self, image_path: Path) -> list[object]: ...
```

`PaddleOcrProvider` implements this contract and hides PaddleOCR result object details from controllers. Tests use fake providers implementing the same `predict()` method.

`app/services/image_service.py` owns image suffix validation, safe filename handling, empty-file checks, and saving uploaded files. It must use a safe filename function before writing uploaded names to disk.

### Models

`app/models/ocr_models.py` contains the internal domain dataclasses and related OCR structures, including equivalents of:

- `OcrItem`
- `FieldResult`
- `FieldQuality`

The existing field extraction and quality rules should keep using these model types so tests can continue to assert exact field values, confidence, sources, and `need_confirm` behavior.

### Repositories

`app/repositories/ocr_result_repository.py` is the storage boundary. First version behavior:

```text
outputs/requests/<request_id>/
  original/<uploaded-filename>
  label_img/<uploaded-filename>
  report.json
```

The repository returns paths used by the service and persists `report.json`. Future MongoDB support should be implemented by adding or replacing repository methods, not by changing controller code.

Repository contract:

```python
@dataclass(frozen=True)
class OcrRequestWorkspace:
    request_id: str
    root_dir: Path
    original_dir: Path
    label_image_dir: Path
    report_path: Path
    original_key: str
    label_image_key: str
    report_key: str

class OcrResultRepository:
    def create_workspace(self, request_id: str, filename: str) -> OcrRequestWorkspace: ...
    def save_original(self, workspace: OcrRequestWorkspace, file_storage) -> Path: ...
    def save_report(self, workspace: OcrRequestWorkspace, report: dict[str, object]) -> Path: ...
```

The service may pass `workspace.label_image_dir / filename` to the visualization service. API responses should expose `original_key`, `label_image_key`, and `report_key` under an `artifacts` object. These keys are storage identifiers such as `requests/<request_id>/label_img/<filename>`, not absolute local paths. This keeps the API stable when storage later moves to MongoDB or object storage.

### Schemas

`app/schemas/response_schema.py` defines the unified response shape:

```json
{
  "code": 0,
  "content": {},
  "message": ""
}
```

`app/schemas/ocr_schema.py` defines upload validation and OpenAPI response structure for the OCR endpoint. Schema helpers should validate only HTTP boundary concerns such as missing image, empty upload, and unsupported suffix.

Schema/OpenAPI implementation choice: hand-written Python dictionaries and small validation functions. Do not introduce Marshmallow, Pydantic, apispec, or Swagger UI in the first refactor because the first version has only one endpoint and a fixed response wrapper.

### Views

`app/views/json_response.py` provides helpers for success and error responses:

```python
success(content) -> ({"code": 0, "content": content, "message": ""}, 200)
error(code, message, status_code) -> ({"code": code, "content": {}, "message": message}, status_code)
```

## API design

### OCR endpoint

```http
POST /api/v1/ocr/orders
Content-Type: multipart/form-data

image=<single image file>
```

Successful response:

```json
{
  "code": 0,
  "content": {
    "request_id": "uuid",
    "fields": {
      "号码": {
        "value": "13800001234",
        "confidence": 0.99,
        "box": [10.0, 10.0, 120.0, 30.0],
        "source": "label_value",
        "candidates": ["13800001234"],
        "need_confirm": false
      }
    },
    "field_quality": {
      "score": 12.5,
      "acceptable": true,
      "valid_fields": {
        "号码": true,
        "日期": true,
        "姓名": true,
        "套餐信息": true
      },
      "reasons": {
        "号码": "valid_phone",
        "日期": "valid_date",
        "姓名": "valid_name",
        "套餐信息": "valid_package"
      }
    },
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

Error responses use the same wrapper. In the first version, `code` matches the HTTP status code for transport/boundary errors and `500` for unexpected server errors.

Missing image response:

```json
{
  "code": 400,
  "content": {},
  "message": "image is required"
}
```

Unsupported file response:

```json
{
  "code": 400,
  "content": {},
  "message": "unsupported image type"
}
```

Required error mapping:

| Case | HTTP status | body `code` | message |
| --- | --- | --- | --- |
| Missing `image` field | 400 | 400 | `image is required` |
| Empty upload filename or zero-byte body | 400 | 400 | `image is empty` |
| Unsupported suffix | 400 | 400 | `unsupported image type` |
| Request exceeds `MAX_CONTENT_LENGTH` | 413 | 413 | `image is too large` |
| Pillow cannot open/process the image | 400 | 400 | `invalid image file` |
| Model directory/config missing at provider init | 500 | 500 | `ocr model is unavailable` |
| OCR provider raises during prediction | 500 | 500 | `ocr processing failed` |
| Repository cannot write original/report/label image | 500 | 500 | `failed to persist ocr result` |

### OpenAPI endpoint

```http
GET /api/v1/openapi.json
```

This endpoint returns a static OpenAPI JSON document containing at least:

- API title and version.
- `POST /api/v1/ocr/orders` path.
- multipart `image` request body.
- wrapped success response.
- wrapped error response.

## Data flow

```text
HTTP multipart request
  -> ocr_controller validates request boundary
  -> ocr_schema validates upload shape and suffix
  -> ocr_service creates request_id
  -> repository creates outputs/requests/<request_id>/
  -> image_service stores original image
  -> paddle_ocr_provider runs OCR
  -> ocr result normalization produces OcrItem values
  -> field extraction builds FieldResult values
  -> field quality builds FieldQuality and calibrates fields
  -> visualization writes label image
  -> repository writes report.json
  -> service returns content with artifact keys
  -> json_response wraps content as {code, content, message}
```

## OCR behavior to preserve

The refactor must preserve the current domain behavior:

- Supported image suffixes: `.jpg`, `.jpeg`, `.png`, `.webp`.
- EXIF orientation normalization.
- Orientation candidates: `0`, `90`, `180`, `270`.
- Stop after 0 degrees if field quality is acceptable.
- Choose best candidate by quality score, then lower rotation cost.
- Normalize PaddleOCR result variants into stable OCR items.
- Extract fields in this priority order for trusted validation/test mode:
  1. inline label-value
  2. row label-value
  3. pattern fallback
  4. filename fallback for `号码`
  5. missing field result
- For API uploads, filename fallback for `号码` is disabled by default. The service should call field extraction with `allow_filename_fallback=False` because client-provided upload filenames are not trusted business data. Tests may enable the fallback explicitly to preserve coverage of the legacy validation behavior.
- Keep `need_confirm = confidence < 0.9`.
- Keep quality rejection behavior by lowering invalid field confidence and appending `:quality_rejected` to `source`.

## Runtime risks and constraints

- PaddleOCR model loading must not happen per request. The app should create a lazy provider once per Flask process and reuse it.
- Flask debug mode may run a reloader process and initialize the provider more than once. This is acceptable for development and should be documented, but not treated as per-request behavior.
- The first request may be slow because it may trigger lazy model initialization.
- The synchronous endpoint can take several seconds per image. This is accepted for the first version; async jobs are explicitly out of scope.
- The implementation should not claim concurrency guarantees beyond what the selected Flask server provides. Production deployment choices are out of scope for this refactor.
- All request-specific files must live under `outputs/requests/<request_id>/` to avoid collisions between simultaneous requests in the same process.

## Packaging and entrypoints

`pyproject.toml` should change from the old `src/unicom_ocr_detect` package to the new `app` package. It should remove:

```toml
[project.scripts]
ocr-validate = "unicom_ocr_detect.run_validation:main"
```

The project should depend on Flask and expose the Flask application via `app:create_app`. Development can run the app with:

```bash
uv run flask --app app run
```

There should be no supported CLI validation command after the refactor.

## Testing plan

Existing behavior tests should be migrated to the new imports and preserved:

- Image suffix discovery/validation.
- PaddleOCR result normalization.
- Field extraction for same-row label-value pairs.
- Phone cleanup from strings like `13800001234复制`.
- Filename phone fallback for trusted validation/test mode, plus API-mode extraction with filename fallback disabled.
- Customer name aliases.
- Inline label-value extraction.
- Timestamp priority over top filter date ranges.
- Compact timestamp spacing.
- Model name loading from `inference.yml`.
- Field quality rejection.
- Orientation candidate fallback.

New API tests should use Flask test client and fake OCR provider:

- `POST /api/v1/ocr/orders` without `image` returns wrapped 400.
- Empty file upload returns wrapped 400.
- Unsupported suffix returns wrapped 400.
- Oversized request triggers wrapped 413.
- Invalid image content returns wrapped 400.
- Valid upload returns wrapped 200 with `request_id`, `fields`, `field_quality`, `raw_ocr`, `selected_rotation_degrees`, and `artifacts`.
- Response `artifacts` contains storage keys, not absolute local filesystem paths.
- The repository writes `original/<filename>`, `label_img/<filename>`, and `report.json` under a request directory.
- Uploaded filenames are sanitized so names like `../../x.jpg` cannot escape the request directory.
- API-mode extraction does not use the uploaded filename as phone fallback.
- Fake provider verifies that when the 0-degree candidate is acceptable, the service does not request 90/180/270 candidates.
- Provider initialization is injected and reused in tests so real PaddleOCR is not loaded.
- Provider exceptions return wrapped 500.
- Repository write failures return wrapped 500.
- `GET /api/v1/openapi.json` returns a JSON document containing `/api/v1/ocr/orders`, multipart `image`, and wrapped success/error schemas.

## Migration notes

Because the new package path is `app/`, all imports should use `app.*`. The old `src/unicom_ocr_detect` package should be removed once tests pass against `app.*`.

`outputs/requests/` is runtime output. It should remain ignored by git just like current `outputs/` artifacts.

The current `CLAUDE.md` and project docs that mention the CLI should be updated after the implementation so future agents use the Flask API entrypoint instead of `ocr-validate`.

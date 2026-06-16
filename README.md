# unicom-ocr-detect

Flask JSON API for recognizing China Unicom mobile App order screenshots/photos.

The service accepts one uploaded image, runs local PaddleOCR models on CPU, extracts the target fields (`号码`, `日期`, `姓名`, `套餐信息`), and returns a wrapped JSON response. Per-request artifacts are saved under `outputs/requests` for inspection.

## Quick start

```bash
uv sync
uv run pytest -q
uv run flask --app app run
```

The project no longer provides a supported CLI entrypoint such as `ocr-validate`.

## API

### Recognize an order image

```http
POST /api/v1/ocr/orders
Content-Type: multipart/form-data
```

Form field:

- `image`: required image upload. Supported suffixes are `.jpg`, `.jpeg`, `.png`, and `.webp`.

Example:

```bash
curl -X POST \
  -F "image=@data/validation/example.jpg" \
  http://127.0.0.1:5000/api/v1/ocr/orders
```

Successful responses are wrapped as:

```json
{
  "code": 0,
  "content": {
    "request_id": "...",
    "fields": {},
    "field_quality": {},
    "raw_ocr": [],
    "selected_rotation_degrees": 0,
    "artifacts": {}
  },
  "message": ""
}
```

Request errors return the same wrapper shape with non-zero `code`, empty `content`, and a message such as `image is required`, `unsupported image type`, or `invalid image file`.

### OpenAPI schema

```http
GET /api/v1/openapi.json
```

Returns the hand-written OpenAPI schema wrapped in the standard JSON response envelope.

## Defaults

- Text detection model: `models/PP-OCRv6_small_det_infer`
- Text recognition model: `models/PP-OCRv6_medium_rec`
- Request artifacts: `outputs/requests/<request-id>/`
- Original uploads: `outputs/requests/<request-id>/original/`
- Label images: `outputs/requests/<request-id>/label_img/`
- JSON report: `outputs/requests/<request-id>/report.json`
- Upload size limit: 20 MiB

PaddleOCR model directories must contain `inference.yml`; the service reads `Global.model_name` from that file instead of hard-coding model names.

## OCR behavior

For each request, the service normalizes image orientation, tries the 0-degree candidate first, normalizes PaddleOCR output into stable OCR items, extracts the four target fields, evaluates field quality, and only tries 90/180/270-degree fallback candidates when the 0-degree result is not acceptable.

Label images use blue boxes for all OCR text regions and red boxes for extracted field value regions. If a rotated candidate is selected, the label image is saved in that selected orientation so boxes line up with the visual content.

## Known caveat

`日期` is currently extracted by prioritizing order-like timestamps over top filter date ranges. It is still marked as `need_confirm=true` until the business definition of `日期` is finalized.

## Documentation

- [需求评估与落地计划](doc/ocr-requirement-evaluation-plan.md)
- [第一阶段验证报告](doc/phase-one-validation-report.md)
- [当前阶段识别过程技术文档](doc/current-stage-recognition-process.md)

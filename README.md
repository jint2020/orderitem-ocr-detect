# unicom-ocr-detect

Flask JSON API for recognizing China Unicom mobile App order screenshots/photos.

The service accepts one uploaded image, runs local PaddleOCR models on CPU, extracts the target fields (`号码`, `日期`, `姓名`, `套餐信息`), and returns a wrapped JSON response with a base64-encoded label image inline. No artifacts are persisted to disk.

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

Query parameter:

- `label_image`: optional, defaults to `true`. Set to `false` to omit the base64 label image from the response.

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
    "label_image_base64": "..."
  },
  "message": ""
}
```

When `label_image=false` is passed, the `label_image_base64` key is omitted entirely.

Request errors return the same wrapper shape with non-zero `code`, empty `content`, and a message such as `image is required`, `unsupported image type`, or `invalid image file`.

### OpenAPI schema

```http
GET /api/v1/openapi.json
```

Returns the hand-written OpenAPI schema wrapped in the standard JSON response envelope.

## Defaults

- Text detection model: `models/PP-OCRv6_small_det_infer`
- Text recognition model: `models/PP-OCRv6_medium_rec`
- Upload size limit: 20 MiB

PaddleOCR model directories must contain `inference.yml`; the service reads `Global.model_name` from that file instead of hard-coding model names.

## OCR behavior

For each request, the service normalizes image orientation, tries the 0-degree candidate first, normalizes PaddleOCR output into stable OCR items, extracts the four target fields, evaluates field quality, and only tries 90/180/270-degree fallback candidates when the 0-degree result is not acceptable.

Label images use blue boxes for all OCR text regions and red boxes for extracted field value regions. If a rotated candidate is selected, the label image is rendered in that selected orientation so boxes line up with the visual content. The label image is returned inline as `label_image_base64`; nothing is written to disk. Pass `label_image=false` to skip rendering it.

## Known caveat

`日期` is currently extracted by prioritizing order-like timestamps over top filter date ranges. It is still marked as `need_confirm=true` until the business definition of `日期` is finalized.

## Deployment (Docker Compose)

The service ships as a stateless container. Models are bind-mounted read-only; no other volumes are needed.

Prerequisites:

- Docker with Compose.
- PaddleOCR models downloaded under `models/` (see `models/README.md`). The service expects `models/PP-OCRv6_small_det_infer`, `models/PP-OCRv6_medium_rec`, and `models/PP-LCNet_x1_0_doc_ori`, each containing `inference.yml`. Note that the detection model's ModelScope repository is named `PP-OCRv6_small_det` — rename the clone to match the expected directory, or override `DETECTION_MODEL_DIR`.
- The image targets `linux/amd64` because PaddlePaddle only publishes x86_64 Linux wheels. On Apple Silicon, enable Rosetta for x86/amd64 emulation in Docker Desktop (Settings -> "Use Rosetta for x86_64/amd64 emulation") for acceptable performance.

Build and run:

```bash
docker compose up --build -d
```

For a step-by-step Ubuntu Server 24.04 LTS walkthrough (model download, `.env`, firewall, troubleshooting), see [docs/deploy-ubuntu.md](docs/deploy-ubuntu.md).

The API is then available at `http://localhost:8080` (override the host port with `OCR_PORT`):

```bash
curl -X POST -F "image=@data/validation/example.jpg" http://localhost:8080/api/v1/ocr/orders
curl -X POST -F "image=@data/validation/example.jpg" "http://localhost:8080/api/v1/ocr/orders?label_image=false"
```

Configuration via environment (set in `docker-compose.yml` or a `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `OCR_PORT` | `8080` | Host port mapped to the container's 5000 |
| `GUNICORN_WORKERS` | `2` | Gunicorn workers; each loads its own PaddleOCR model on first request |
| `DETECTION_MODEL_DIR` | `models/PP-OCRv6_small_det_infer` | Detection model directory |
| `RECOGNITION_MODEL_DIR` | `models/PP-OCRv6_medium_rec` | Recognition model directory |
| `DOC_ORIENTATION_MODEL_DIR` | `models/PP-LCNet_x1_0_doc_ori` | Document orientation classifier directory |
| `MAX_CONTENT_LENGTH` | `20971520` (20 MiB) | Max upload size in bytes |

Notes:

- The container is stateless: uploaded images are processed in a temporary directory removed per request. No `outputs/` volume is needed.
- The first OCR request after start (per worker) is slow because PaddleOCR loads lazily; raise `--timeout` if you increase model size or worker count.
- On macOS, port 5000 (AirPlay Receiver) and 8000 (OrbStack) are commonly occupied, so the default host port is `8080`. Override with `OCR_PORT`.

## Documentation

- [当前阶段识别过程技术文档](doc/ocr流程.md)（本地文件，未纳入 git）

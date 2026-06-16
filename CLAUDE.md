# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

- Install/sync dependencies: `uv sync`
- Run the full test suite: `uv run pytest -q`
- Run API tests only: `uv run pytest -q tests/test_api.py`
- Run service/domain tests only: `uv run pytest -q tests/test_validation_harness.py`
- Start the Flask development server: `uv run flask --app app run`

There is no supported CLI entrypoint. Do not use or reintroduce `ocr-validate`.

## Project purpose

This repository provides a Flask JSON API for China Unicom mobile App order screenshots/photos. It accepts one uploaded image, runs local PaddleOCR models on CPU, extracts four business fields (`号码`, `日期`, `姓名`, `套餐信息`), and returns wrapped JSON while persisting per-request artifacts for inspection.

## High-level architecture

The application uses a small Flask MVC-style layout under `app/`:

1. `app/__init__.py` creates the Flask app, loads config, registers the v1 API blueprint, and wires OCR provider/repository dependencies.
2. `app/controllers/api/v1/ocr_controller.py` exposes `POST /api/v1/ocr/orders` and `GET /api/v1/openapi.json`.
3. `app/services/ocr_service.py` orchestrates single-upload OCR: save upload, run orientation candidates, normalize OCR results, extract fields, apply quality checks, save report and label image, and return API content.
4. `app/services/field_extraction.py`, `field_quality.py`, `image_service.py`, `orientation_service.py`, `paddle_ocr_provider.py`, and `visualization_service.py` contain pure OCR/domain behavior and PaddleOCR integration.
5. `app/models/ocr_models.py` contains stable OCR and field result data structures.
6. `app/repositories/ocr_result_repository.py` persists request workspaces under `outputs/requests`.
7. `app/schemas/ocr_schema.py` and `app/views/json_response.py` define request/OpenAPI helpers and the `{code, content, message}` JSON envelope.

## Data, models, and outputs

Default paths and limits:

- Detection model: `models/PP-OCRv6_small_det_infer`
- Recognition model: `models/PP-OCRv6_medium_rec`
- Request artifacts: `outputs/requests/<request-id>/`
- Original upload: `outputs/requests/<request-id>/original/<filename>`
- Label image: `outputs/requests/<request-id>/label_img/<filename>`
- Report JSON: `outputs/requests/<request-id>/report.json`
- Upload size limit: 20 MiB

PaddleOCR model directories must contain `inference.yml`; the code reads `Global.model_name` from that file instead of hard-coding model names.

Each saved report includes the request id, original image path, elapsed time, selected rotation, field quality, compact orientation-candidate summaries, extracted fields, label image path, artifacts, and raw normalized OCR items.

## Current caveats

- `日期` is currently extracted by prioritizing order-like timestamps over top filter date ranges, but it is still marked as needing confirmation until the business definition is finalized.
- Multi-angle OCR only runs when the 0-degree candidate fails field-quality checks; rotated cases can cost multiple OCR passes on CPU.
- The service is synchronous and processes one uploaded image per request.

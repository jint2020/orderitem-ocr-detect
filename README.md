# unicom-ocr-detect

First-phase OCR validation harness for mobile App order screenshots/photos.

The quick validation reads images from `data/validation`, runs PaddleOCR with the local
`models/PP-OCRv6_medium_rec` recognition model, extracts target fields, and writes JSON
reports under `outputs/validation`.

## Quick validation

```bash
uv sync
uv run pytest -q
uv run ocr-validate
```

The validation runner uses:

- Text detection: `models/PP-OCRv6_small_det_infer`
- Text recognition: `models/PP-OCRv6_medium_rec`
- Orientation handling: EXIF normalization plus 0/90/180/270 fallback when field quality is poor
- Images: `data/validation`
- Reports: `outputs/validation`
- Label images: `outputs/validation/label_img`

## CLI options

```bash
uv run ocr-validate \
  --images data/validation \
  --det-model-dir models/PP-OCRv6_small_det_infer \
  --rec-model-dir models/PP-OCRv6_medium_rec \
  --output-dir outputs/validation
```

Use `--limit N` for a fast smoke run:

```bash
uv run ocr-validate --limit 1
```

## Runtime logs

The CLI writes progress logs to stdout with the `[ocr-validate]` prefix. The logs show:

- validation start, input directory, output directory
- detection and recognition model directories
- orientation candidate score and selected rotation
- per-image start and completion
- per-image OCR item count, populated field count, confirmation count, elapsed time
- per-image JSON report path
- per-image label image path
- final summary path and aggregate counts

Example:

```text
[ocr-validate] start images=5 input_dir=data/validation output_dir=outputs/validation
[ocr-validate] model det_dir=models/PP-OCRv6_small_det_infer rec_dir=models/PP-OCRv6_medium_rec device=cpu
[ocr-validate] image start 1/5 13242337390.jpg
[ocr-validate] orientation candidate rotation=0 score=12.9375 acceptable=True valid={'号码': True, '日期': True, '姓名': True, '套餐信息': True}
[ocr-validate] orientation selected rotation=0 score=12.9375 acceptable=True
[ocr-validate] image done 1/5 13242337390.jpg elapsed=5.52s ocr_items=49 populated=4/4 need_confirm=1/4
[ocr-validate] report written outputs/validation/13242337390.json
[ocr-validate] label image written outputs/validation/label_img/13242337390.jpg
[ocr-validate] summary images=5 elapsed=26.78s avg=5.36s populated={'号码': 5, '日期': 5, '姓名': 5, '套餐信息': 5} need_confirm={'号码': 0, '日期': 5, '姓名': 0, '套餐信息': 0}
[ocr-validate] summary written outputs/validation/summary.json
```

To save logs while still seeing them in the terminal:

```bash
uv run ocr-validate 2>&1 | tee outputs/validation/run.log
```

## Output files

Each image produces one JSON report:

```text
outputs/validation/<image-name>.json
```

Each report contains:

- `image`: original image path
- `elapsed_seconds`: per-image runtime
- `selected_rotation_degrees`: selected OCR input rotation
- `field_quality`: business-level field quality score and validity reasons
- `orientation_candidates`: compact comparison of tried rotations
- `label_image`: visualized image path under `outputs/validation/label_img`
- `fields`: extracted `号码`、`日期`、`姓名`、`套餐信息`
- `raw_ocr`: normalized OCR text, confidence, and boxes

Visualized label images are written to:

```text
outputs/validation/label_img/<image-name>
```

The label images use blue boxes for all OCR text regions and red boxes for extracted field value regions. If a rotated candidate is selected, the label image is saved in that selected orientation so boxes line up with the visual content.

The aggregate report is:

```text
outputs/validation/summary.json
```

## Known caveat

`日期` is currently extracted by prioritizing order-like timestamps over top filter date ranges. It is still marked as `need_confirm=true` until the business definition of `日期` is finalized.

## Documentation

- [需求评估与落地计划](doc/ocr-requirement-evaluation-plan.md)
- [第一阶段验证报告](doc/phase-one-validation-report.md)
- [当前阶段识别过程技术文档](doc/current-stage-recognition-process.md)

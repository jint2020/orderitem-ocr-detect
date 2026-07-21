import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from werkzeug.datastructures import FileStorage

from app.models.ocr_models import extract_orientation_angle, normalize_paddle_result
from app.services.field_extraction import extract_fields
from app.services.field_quality import apply_quality_to_fields, evaluate_fields
from app.services.image_service import secure_upload_filename
from app.services.visualization_service import render_label_image


class OcrProcessingError(RuntimeError):
    pass


class OcrService:
    def __init__(self, provider: Any):
        self.provider = provider

    def recognize_order_image(
        self,
        file_storage: FileStorage,
        request_id: str | None = None,
        include_label_image: bool = True,
    ) -> dict[str, Any]:
        request_id = request_id or str(uuid4())
        with TemporaryDirectory(prefix="unicom-ocr-") as temp_dir:
            original_path = (
                Path(temp_dir)
                / "original"
                / secure_upload_filename(file_storage.filename or "upload.jpg")
            )
            original_path.parent.mkdir(parents=True, exist_ok=True)
            file_storage.stream.seek(0)
            file_storage.save(original_path)

            # 单次 OCR：PaddleOCR 内部用方向分类器把图旋正后再 det+rec，
            # 替代原先 0/90/180/270 四次全量 OCR。框在旋正后坐标系。
            ocr_items, selected_rotation = self._run_ocr(original_path)
            raw_fields = extract_fields(
                ocr_items,
                image_path=original_path,
                allow_filename_fallback=False,
            )
            quality = evaluate_fields(raw_fields)
            fields = apply_quality_to_fields(raw_fields, quality)

            content: dict[str, Any] = {
                "request_id": request_id,
                "fields": {
                    name: result.to_dict() for name, result in fields.items()
                },
                "field_quality": quality.to_dict(),
                "raw_ocr": [item.to_dict() for item in ocr_items],
                "selected_rotation_degrees": selected_rotation,
            }
            if include_label_image:
                label_image_bytes = render_label_image(
                    original_path,
                    ocr_items,
                    fields,
                    rotation_degrees=selected_rotation,
                )
                content["label_image_base64"] = base64.b64encode(label_image_bytes).decode("ascii")

        return content

    def _run_ocr(self, image_path: Path) -> tuple[list[Any], int]:
        try:
            raw_results = self.provider.predict(image_path)
        except Exception as exc:
            raise OcrProcessingError("ocr processing failed") from exc
        ocr_items: list[Any] = []
        selected_rotation = 0
        for raw_result in raw_results:
            ocr_items.extend(normalize_paddle_result(raw_result))
            selected_rotation = extract_orientation_angle(raw_result) or selected_rotation
        return ocr_items, selected_rotation

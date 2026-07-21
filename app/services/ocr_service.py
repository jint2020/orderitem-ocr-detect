import base64
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from werkzeug.datastructures import FileStorage

from app.models.ocr_models import (
    FieldQuality,
    FieldResult,
    OcrItem,
    extract_orientation_angle,
    normalize_paddle_result,
)
from app.services.field_extraction import extract_fields
from app.services.field_quality import apply_quality_to_fields, evaluate_fields
from app.services.image_service import secure_upload_filename
from app.services.visualization_service import render_label_image


class OcrProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class _OcrPass:
    """One OCR attempt: items, detected rotation, extracted fields and quality."""

    items: list[OcrItem]
    rotation: int
    fields: dict[str, FieldResult]
    quality: FieldQuality


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

            # 混合策略：先 plain 0°（关分类器，最快），通过质量门直接返回；
            # 否则回退到方向分类器再跑一次，按质量分挑更好的那个返回。最坏 2 次。
            ocr_pass = self._run_ocr(original_path)
            ocr_items = ocr_pass.items
            selected_rotation = ocr_pass.rotation
            raw_fields = ocr_pass.fields
            quality = ocr_pass.quality
            fields = apply_quality_to_fields(raw_fields, quality)

            content: dict[str, Any] = {
                "request_id": request_id,
                "fields": {
                    name: result.to_dict() for name, result in fields.items()
                },
                "field_quality": quality.to_dict(),
                # 不返回所有box 无意义
                # "raw_ocr": [item.to_dict() for item in ocr_items],
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

    def _run_ocr(self, image_path: Path) -> _OcrPass:
        # Pass 1: plain 0°（不启用方向分类器）。直立图常见，单次即过质量门。
        plain = self._ocr_pass(image_path, use_classifier=False)
        if plain.quality.acceptable:
            return plain
        # Pass 2: plain 不过质量门，回退方向分类器，按质量分挑更好的返回。
        classified = self._ocr_pass(image_path, use_classifier=True)
        if classified.quality.score > plain.quality.score:
            return classified
        return plain

    def _ocr_pass(self, image_path: Path, use_classifier: bool) -> _OcrPass:
        try:
            raw_results = self.provider.predict(image_path, use_classifier=use_classifier)
        except Exception as exc:
            raise OcrProcessingError("ocr processing failed") from exc
        items: list[OcrItem] = []
        rotation = 0
        for raw_result in raw_results:
            items.extend(normalize_paddle_result(raw_result))
            rotation = extract_orientation_angle(raw_result) or rotation
        fields = extract_fields(items, image_path=image_path, allow_filename_fallback=False)
        quality = evaluate_fields(fields)
        return _OcrPass(items=items, rotation=rotation, fields=fields, quality=quality)

import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from werkzeug.datastructures import FileStorage

from app.models.ocr_models import normalize_paddle_result
from app.services.field_extraction import extract_fields
from app.services.field_quality import apply_quality_to_fields, evaluate_fields
from app.services.image_service import secure_upload_filename
from app.services.orientation_service import iter_orientation_images
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
                Path(temp_dir) / "original" / secure_upload_filename(file_storage.filename or "upload.jpg")
            )
            original_path.parent.mkdir(parents=True, exist_ok=True)
            file_storage.stream.seek(0)
            file_storage.save(original_path)

            candidate = self._select_orientation_candidate(original_path)
            content: dict[str, Any] = {
                "request_id": request_id,
                "fields": {
                    name: result.to_dict() for name, result in candidate["fields"].items()
                },
                "field_quality": candidate["quality"].to_dict(),
                "raw_ocr": [item.to_dict() for item in candidate["ocr_items"]],
                "selected_rotation_degrees": candidate["rotation_degrees"],
            }
            if include_label_image:
                label_image_bytes = render_label_image(
                    original_path,
                    candidate["ocr_items"],
                    candidate["fields"],
                    rotation_degrees=candidate["rotation_degrees"],
                )
                content["label_image_base64"] = base64.b64encode(label_image_bytes).decode("ascii")

        return content

    def _select_orientation_candidate(self, image_path: Path) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        try:
            for rotation, candidate_path in iter_orientation_images(image_path):
                raw_results = self.provider.predict(candidate_path)
                ocr_items: list[Any] = []
                for raw_result in raw_results:
                    ocr_items.extend(normalize_paddle_result(raw_result))

                raw_fields = extract_fields(
                    ocr_items,
                    image_path=image_path,
                    allow_filename_fallback=False,
                )
                quality = evaluate_fields(raw_fields)
                fields = apply_quality_to_fields(raw_fields, quality)
                candidates.append(
                    {
                        "rotation_degrees": rotation,
                        "ocr_items": ocr_items,
                        "fields": fields,
                        "quality": quality,
                    }
                )
                if rotation == 0 and quality.acceptable:
                    break
        except Exception as exc:
            raise OcrProcessingError("ocr processing failed") from exc

        if not candidates:
            raise OcrProcessingError("ocr processing failed")

        return max(
            candidates,
            key=lambda item: (item["quality"].score, -_rotation_cost(item["rotation_degrees"])),
        )


def _rotation_cost(rotation: int) -> int:
    return min(rotation % 360, (-rotation) % 360)

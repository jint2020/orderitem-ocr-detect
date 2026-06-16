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

        if not candidates:
            raise OcrProcessingError("ocr processing failed")

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

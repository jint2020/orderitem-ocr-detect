"""Lazy PaddleOCR provider wrapper for OCR services."""

from pathlib import Path
from typing import Any, Protocol

import yaml


class OcrProvider(Protocol):
    def predict(self, image_path: Path) -> list[Any]: ...


class PaddleOcrProvider:
    def __init__(self, det_model_dir: Path, rec_model_dir: Path):
        self.det_model_dir = det_model_dir
        self.rec_model_dir = rec_model_dir
        self._ocr: Any | None = None

    def predict(self, image_path: Path) -> list[Any]:
        return self._get_ocr().predict(str(image_path))

    def _get_ocr(self):
        if self._ocr is None:
            self._ocr = build_paddleocr(self.det_model_dir, self.rec_model_dir)
        return self._ocr


def build_paddleocr(det_model_dir: Path, rec_model_dir: Path):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=read_model_name(det_model_dir),
        text_detection_model_dir=str(det_model_dir),
        text_recognition_model_name=read_model_name(rec_model_dir),
        text_recognition_model_dir=str(rec_model_dir),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
    )


def read_model_name(model_dir: Path) -> str:
    config_path = model_dir / "inference.yml"
    if not config_path.exists():
        raise FileNotFoundError(f"Model config does not exist: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    model_name = config.get("Global", {}).get("model_name")
    if not model_name:
        raise ValueError(f"Global.model_name missing in {config_path}")
    return str(model_name)

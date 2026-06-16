"""Stable OCR domain models and PaddleOCR result normalization."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OcrItem:
    """Internal OCR text item used by extraction and reporting code."""

    text: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def center_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.box[3] - self.box[1])

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "score": self.score, "box": [round(value, 2) for value in self.box]}


@dataclass(frozen=True)
class FieldResult:
    """Single extracted business field."""

    value: str
    confidence: float
    box: tuple[float, float, float, float] | None
    source: str
    candidates: tuple[str, ...] = ()

    @property
    def need_confirm(self) -> bool:
        return self.confidence < 0.9

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "box": [round(value, 2) for value in self.box] if self.box else None,
            "source": self.source,
            "candidates": list(self.candidates),
            "need_confirm": self.need_confirm,
        }


@dataclass(frozen=True)
class FieldQuality:
    """Quality assessment for a set of extracted fields."""

    score: float
    acceptable: bool
    valid_fields: dict[str, bool]
    reasons: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "acceptable": self.acceptable,
            "valid_fields": self.valid_fields,
            "reasons": self.reasons,
        }


def normalize_paddle_result(raw_result: Any) -> list[OcrItem]:
    """Convert one PaddleOCR result object into stable ``OcrItem`` values."""
    data = _to_mapping(raw_result)
    res = data.get("res", data)
    texts = res.get("rec_texts") or res.get("dt_texts") or []
    scores = res.get("rec_scores") or res.get("dt_scores") or []
    polys = res.get("rec_polys") or res.get("dt_polys") or res.get("polys") or []

    items: list[OcrItem] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        score = float(scores[index]) if index < len(scores) else 0.0
        poly = polys[index] if index < len(polys) else None
        box = _poly_to_box(poly)
        items.append(OcrItem(text=str(text).strip(), score=score, box=box))
    return items


def _to_mapping(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    if hasattr(raw_result, "json"):
        value = raw_result.json
        if isinstance(value, dict):
            return value
    if hasattr(raw_result, "res"):
        value = raw_result.res
        if isinstance(value, dict):
            return {"res": value}
    if hasattr(raw_result, "__dict__"):
        value = vars(raw_result)
        if isinstance(value, dict):
            return value
    raise TypeError(f"Unsupported PaddleOCR result type: {type(raw_result)!r}")


def _poly_to_box(poly: Any) -> tuple[float, float, float, float]:
    if poly is None:
        return (0.0, 0.0, 0.0, 0.0)
    points = list(poly)
    if len(points) == 4 and all(isinstance(value, (int, float)) for value in points):
        x1, y1, x2, y2 = [float(value) for value in points]
        return (x1, y1, x2, y2)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (min(xs), min(ys), max(xs), max(ys))

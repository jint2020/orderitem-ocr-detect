"""Business-quality validation for extracted OCR fields."""

from __future__ import annotations

import re

from app.models.ocr_models import FieldQuality, FieldResult
from app.services.field_extraction import PHONE_RE, TARGET_FIELDS


DATE_VALUE_RE = re.compile(r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?")
TIME_VALUE_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
MASKED_NAME_RE = re.compile(r"^[一-鿿A-Za-z][一-鿿A-Za-z*＊·]{0,8}$")
NOISY_VALUE_TOKENS = ("请输入", "订单编号", "筛选", "搜索", "已完成", "复制")


def evaluate_fields(fields: dict[str, FieldResult]) -> FieldQuality:
    """Evaluate whether extracted fields are plausible business values."""
    valid_fields: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    score = 0.0

    for field_name in TARGET_FIELDS:
        result = fields[field_name]
        valid, reason = _validate_field(field_name, result.value)
        valid_fields[field_name] = valid
        reasons[field_name] = reason

        if result.value:
            score += 1.0
        if valid:
            score += 2.0
        score += max(0.0, min(result.confidence, 1.0)) * 0.25

    required_fields = ("号码", "日期", "姓名", "套餐信息")
    acceptable = all(valid_fields[field_name] for field_name in required_fields)
    return FieldQuality(score=score, acceptable=acceptable, valid_fields=valid_fields, reasons=reasons)


def apply_quality_to_fields(
    fields: dict[str, FieldResult],
    quality: FieldQuality,
) -> dict[str, FieldResult]:
    """Lower confidence for fields rejected by business-quality checks."""
    calibrated: dict[str, FieldResult] = {}
    for field_name, result in fields.items():
        if quality.valid_fields.get(field_name, False):
            calibrated[field_name] = result
            continue

        calibrated[field_name] = FieldResult(
            value=result.value,
            confidence=min(result.confidence, 0.49),
            box=result.box,
            source=f"{result.source}:quality_rejected",
            candidates=result.candidates,
        )
    return calibrated


def _validate_field(field_name: str, value: str) -> tuple[bool, str]:
    value = value.strip()
    if not value:
        return False, "empty"

    if field_name == "号码":
        if PHONE_RE.fullmatch(value):
            return True, "valid_phone"
        return False, "phone_must_be_11_digits"

    if field_name == "日期":
        if DATE_VALUE_RE.search(value):
            return True, "valid_date"
        return False, "date_pattern_missing"

    if field_name == "姓名":
        if _looks_noisy(value):
            return False, "name_contains_noise"
        if DATE_VALUE_RE.search(value) or PHONE_RE.search(value) or TIME_VALUE_RE.search(value):
            return False, "name_contains_date_or_number"
        if MASKED_NAME_RE.fullmatch(value):
            return True, "valid_name"
        return False, "name_shape_unexpected"

    if field_name == "套餐信息":
        if _looks_noisy(value):
            return False, "package_contains_noise"
        if DATE_VALUE_RE.search(value) or TIME_VALUE_RE.search(value):
            return False, "package_contains_date_or_time"
        if len(value) >= 4 and re.search(r"[一-鿿A-Za-z]", value):
            return True, "valid_package"
        return False, "package_too_short_or_symbolic"

    return True, "unchecked_field"


def _looks_noisy(value: str) -> bool:
    return any(token in value for token in NOISY_VALUE_TOKENS)

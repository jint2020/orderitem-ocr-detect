"""字段结果质量评估。

OCR 模型置信度只说明“这段文字像不像模型看到的文字”，不等于业务字段可信。
例如横置图片中，模型可能高置信识别出一整列文字，但字段抽取把它误配给 `号码`。
本模块用业务格式和轻量文本特征给字段结果做二次校验，供方向选择和前端确认提示使用。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from unicom_ocr_detect.fields import FieldResult, PHONE_RE, TARGET_FIELDS


DATE_VALUE_RE = re.compile(r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?")
TIME_VALUE_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
MASKED_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z*＊·]{0,8}$")

# 这些文本常来自搜索栏、筛选区、订单编号、身份证等 UI/非目标字段。
NOISY_VALUE_TOKENS = ("请输入", "订单编号", "筛选", "搜索", "已完成", "复制")


@dataclass(frozen=True)
class FieldQuality:
    """一组字段结果的质量评分。

    Attributes:
        score: 用于候选方向排序的综合分，越高越好。
        acceptable: 是否足够作为最终结果返回。当前要求目标字段基本齐全且格式校验通过。
        valid_fields: 每个字段是否通过字段级校验。
        reasons: 每个字段的校验说明，写入 JSON 方便排查。
    """

    score: float
    acceptable: bool
    valid_fields: dict[str, bool]
    reasons: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        """转换为报告 JSON 结构。"""
        return {
            "score": round(self.score, 4),
            "acceptable": self.acceptable,
            "valid_fields": self.valid_fields,
            "reasons": self.reasons,
        }


def evaluate_fields(fields: dict[str, FieldResult]) -> FieldQuality:
    """评估字段结果是否可信。

    评分兼顾“字段是否有值”和“值是否符合字段语义”。这样可避免高 OCR 置信度的
    错配结果在方向选择中胜出。
    """
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
    """根据质量校验调整字段置信度。

    不可信字段保留原始 value 和 source，便于人工排查；但置信度会压低到确认阈值以下，
    前端即可把它作为“需要用户确认/修正”的字段展示。
    """
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
    """按字段类型做低风险格式校验。"""
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
        if len(value) >= 4 and re.search(r"[\u4e00-\u9fffA-Za-z]", value):
            return True, "valid_package"
        return False, "package_too_short_or_symbolic"

    return True, "unchecked_field"


def _looks_noisy(value: str) -> bool:
    """判断 value 是否明显混入非目标 UI 文本。"""
    return any(token in value for token in NOISY_VALUE_TOKENS)

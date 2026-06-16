"""Rule-based extraction for China Unicom order OCR fields."""

from pathlib import Path
import re

from app.models.ocr_models import FieldResult, OcrItem

TARGET_FIELDS = ("号码", "日期", "姓名", "套餐信息")

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "号码": ("号码", "手机号", "手机号码", "用户号码", "联系电话", "业务号码", "入网号码", "联系电话号码"),
    "日期": ("日期", "办理日期", "办理时间", "订单日期", "订单时间", "生效日期", "生效时间", "下单时间", "时间"),
    "姓名": ("姓名", "客户姓名", "客户名称", "用户姓名", "用户名称", "联系人", "机主姓名"),
    "套餐信息": ("套餐信息", "套餐", "资费套餐", "产品名称", "套餐名称"),
}

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
DATE_RE = re.compile(r"\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}日?")
TIMESTAMP_RE = re.compile(
    r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s*\d{1,2}:\d{2}:\d{2}"
)


def extract_fields(
    items: list[OcrItem],
    image_path: Path | None = None,
    allow_filename_fallback: bool = False,
) -> dict[str, FieldResult]:
    """Extract target business fields from normalized OCR items."""
    rows = _group_rows(items)
    results: dict[str, FieldResult] = {}

    for field_name in TARGET_FIELDS:
        result = _extract_inline_label_value(field_name, items)
        if result is None:
            result = _extract_from_rows(field_name, rows)
        if result is None:
            result = _extract_by_pattern(field_name, items)
        if (
            result is None
            and field_name == "号码"
            and image_path is not None
            and allow_filename_fallback
        ):
            result = _extract_phone_from_filename(image_path)
        if result is None:
            result = FieldResult("", 0.0, None, "missing", ())
        results[field_name] = result

    return results


def _group_rows(items: list[OcrItem]) -> list[list[OcrItem]]:
    sorted_items = sorted(items, key=lambda item: (item.center_y, item.box[0]))
    rows: list[list[OcrItem]] = []

    for item in sorted_items:
        matched_row = None
        for row in rows:
            avg_y = sum(existing.center_y for existing in row) / len(row)
            avg_height = sum(existing.height for existing in row) / len(row)
            if abs(item.center_y - avg_y) <= max(12.0, avg_height * 0.65):
                matched_row = row
                break
        if matched_row is None:
            rows.append([item])
        else:
            matched_row.append(item)

    for row in rows:
        row.sort(key=lambda item: item.box[0])
    return rows


def _extract_from_rows(field_name: str, rows: list[list[OcrItem]]) -> FieldResult | None:
    aliases = FIELD_ALIASES[field_name]
    for row_index, row in enumerate(rows):
        for item_index, item in enumerate(row):
            if not _looks_like_label(item.text, aliases):
                continue

            candidates = row[item_index + 1 :]
            if not candidates and row_index + 1 < len(rows):
                candidates = rows[row_index + 1]

            value_items = [
                candidate
                for candidate in candidates
                if not _is_any_label(candidate.text) and candidate.text != item.text
            ]
            if not value_items:
                continue

            value = _normalize_field_value(field_name, _join_value_items(value_items))
            confidence = min(item.score, sum(value_item.score for value_item in value_items) / len(value_items))
            return FieldResult(
                value=value,
                confidence=confidence,
                box=_merge_boxes(value_items),
                source="label_value",
                candidates=(value,),
            )
    return None


def _extract_inline_label_value(field_name: str, items: list[OcrItem]) -> FieldResult | None:
    aliases = FIELD_ALIASES[field_name]
    for item in items:
        normalized_text = _normalize_label(item.text)
        for alias in aliases:
            normalized_alias = _normalize_label(alias)
            if not normalized_text.startswith(normalized_alias):
                continue

            value = _normalize_field_value(field_name, _split_inline_value(item.text, alias))
            if not value:
                continue
            return FieldResult(
                value=value,
                confidence=item.score,
                box=item.box,
                source="inline_label_value",
                candidates=(value,),
            )
    return None


def _split_inline_value(text: str, alias: str) -> str:
    patterns = [
        rf"^\s*{re.escape(alias)}\s*[:：]\s*(.+?)\s*$",
        rf"^\s*{re.escape(alias)}\s+(.+?)\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_by_pattern(field_name: str, items: list[OcrItem]) -> FieldResult | None:
    joined = " ".join(item.text for item in items)
    if field_name == "号码":
        match = PHONE_RE.search(joined)
        if match:
            return FieldResult(match.group(0), 0.75, None, "pattern", (match.group(0),))
    if field_name == "日期":
        match = TIMESTAMP_RE.search(joined)
        if match:
            value = _normalize_timestamp(match.group(0))
            return FieldResult(value, 0.85, None, "timestamp_pattern", (value,))
        match = DATE_RE.search(joined)
        if match:
            return FieldResult(match.group(0), 0.75, None, "pattern", (match.group(0),))
    return None


def _extract_phone_from_filename(image_path: Path) -> FieldResult | None:
    match = PHONE_RE.search(image_path.stem)
    if not match:
        return None
    phone = match.group(0)
    return FieldResult(phone, 0.5, None, "filename", (phone,))


def _normalize_timestamp(value: str) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return re.sub(
        r"^(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)(\d{1,2}:\d{2}:\d{2})$",
        r"\1 \2",
        compact,
    )


def _normalize_field_value(field_name: str, value: str) -> str:
    cleaned = value.strip()
    if field_name == "号码":
        match = PHONE_RE.search(cleaned)
        if match:
            return match.group(0)
    if field_name == "日期":
        return _normalize_timestamp(cleaned)
    return cleaned


def _looks_like_label(text: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize_label(text)
    return normalized in {_normalize_label(alias) for alias in aliases}


def _is_any_label(text: str) -> bool:
    return any(_looks_like_label(text, aliases) for aliases in FIELD_ALIASES.values())


def _normalize_label(text: str) -> str:
    return re.sub(r"[\s:：|｜\-_]", "", text)


def _join_value_items(items: list[OcrItem]) -> str:
    return "".join(item.text.strip() for item in items if item.text.strip())


def _merge_boxes(items: list[OcrItem]) -> tuple[float, float, float, float]:
    return (
        min(item.box[0] for item in items),
        min(item.box[1] for item in items),
        max(item.box[2] for item in items),
        max(item.box[3] for item in items),
    )

"""订单页目标字段抽取规则。

OCR 模型只负责输出“图片里有哪些文字，以及文字在哪里”。本模块负责把 OCR
文本进一步解释成业务字段：

- `号码`
- `日期`
- `姓名`
- `套餐信息`

当前阶段采用轻量、可解释的规则链路，而不是端到端 KIE 模型。抽取优先级为：

1. inline label-value：同一个 OCR 文本中直接包含 `label：value`。
2. row label-value：label 和 value 分属同一行或相邻行。
3. pattern fallback：用正则兜底识别手机号、日期。
4. filename fallback：验证阶段用文件名兜底号码。
5. missing：仍未识别则返回空字段。

这些规则服务于第一阶段快速验证。后续接入更多样本和真值标注后，应根据错误类型
继续扩展别名、布局策略，或升级为轻量 KIE。
"""

from dataclasses import dataclass
from pathlib import Path
import re

from unicom_ocr_detect.ocr_result import OcrItem

# 当前业务只需要这四个字段。保持固定顺序可让 JSON 输出、测试和前端展示更稳定。
TARGET_FIELDS = ("号码", "日期", "姓名", "套餐信息")

# 字段别名表负责把页面里的不同 label 归一到目标字段。
# 注意：别名匹配当前使用“归一化后精确匹配”，避免把 value 中的普通词误判为 label。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "号码": ("号码", "手机号", "手机号码", "用户号码", "联系电话", "业务号码", "入网号码", "联系电话号码"),
    "日期": ("日期", "办理日期", "办理时间", "订单日期", "订单时间", "生效日期", "生效时间", "下单时间", "时间"),
    "姓名": ("姓名", "客户姓名", "客户名称", "用户姓名", "用户名称", "联系人", "机主姓名"),
    "套餐信息": ("套餐信息", "套餐", "资费套餐", "产品名称", "套餐名称"),
}

# 当前号码规则只覆盖中国大陆 11 位手机号。宽带号、订单号等其他号码类型需要另加规则。
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 普通日期兜底。这个规则可能命中页面顶部筛选日期，因此优先级低于 TIMESTAMP_RE。
DATE_RE = re.compile(r"\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}日?")

# 订单页中实际订单时间通常带时分秒。当前优先匹配它，以避开顶部日期筛选范围。
TIMESTAMP_RE = re.compile(
    r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s*\d{1,2}:\d{2}:\d{2}"
)


@dataclass(frozen=True)
class FieldResult:
    """单个业务字段的抽取结果。

    Attributes:
        value: 抽取到的字段值；没抽到时为空字符串。
        confidence: 当前阶段规则给出的置信度。它不是模型校准后的概率。
        box: 字段值对应的 OCR 文本框。pattern/filename 兜底时可能为空。
        source: 字段来源，例如 `label_value`、`inline_label_value`、`pattern`。
        candidates: 当前保留的候选值列表。第一阶段通常只有一个候选。
    """

    value: str
    confidence: float
    box: tuple[float, float, float, float] | None
    source: str
    candidates: tuple[str, ...] = ()

    @property
    def need_confirm(self) -> bool:
        """是否建议前端提示用户重点确认。"""
        return self.confidence < 0.9

    def to_dict(self) -> dict[str, object]:
        """转换为 JSON 报告中的字段结构。"""
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "box": [round(value, 2) for value in self.box] if self.box else None,
            "source": self.source,
            "candidates": list(self.candidates),
            "need_confirm": self.need_confirm,
        }


def extract_fields(
    items: list[OcrItem],
    image_path: Path | None = None,
) -> dict[str, FieldResult]:
    """从 OCR 文本项中抽取四个目标字段。

    这里采用逐字段、逐策略的方式，而不是一次性全局解析。这样便于后续针对某个字段
    单独增强规则，例如为 `日期` 增加业务 label 优先级，或为 `套餐信息` 增加多行合并。
    """
    rows = _group_rows(items)
    results: dict[str, FieldResult] = {}

    for field_name in TARGET_FIELDS:
        # 1. 优先处理 `套餐名称：xxx` 这类 label 和 value 在同一个 OCR item 中的情况。
        result = _extract_inline_label_value(field_name, items)
        if result is None:
            # 2. 再处理表单 cell 中最常见的“左 label，右 value”或“上 label，下 value”。
            result = _extract_from_rows(field_name, rows)
        if result is None:
            # 3. 最后使用正则兜底。正则没有明确 label 语义，因此置信度较低。
            result = _extract_by_pattern(field_name, items)
        if result is None and field_name == "号码" and image_path is not None:
            # 4. 文件名兜底只用于当前验证集，因为样本文件名刚好是手机号。
            result = _extract_phone_from_filename(image_path)
        if result is None:
            # 5. 保持字段 key 始终存在，方便前端和评估脚本消费。
            result = FieldResult(
                value="",
                confidence=0.0,
                box=None,
                source="missing",
                candidates=(),
            )
        results[field_name] = result

    return results


def _group_rows(items: list[OcrItem]) -> list[list[OcrItem]]:
    """根据 OCR 文本框坐标粗略重建页面行结构。

    移动端订单页通常是 cell 表单，label 和 value 在同一水平区域内。
    行聚类不追求像素级严格，只需要把视觉上同一行的文字聚到一起。
    """
    sorted_items = sorted(items, key=lambda item: (item.center_y, item.box[0]))
    rows: list[list[OcrItem]] = []

    for item in sorted_items:
        matched_row = None
        for row in rows:
            avg_y = sum(existing.center_y for existing in row) / len(row)
            avg_height = sum(existing.height for existing in row) / len(row)
            # 阈值同时考虑固定像素和文本高度比例，兼容不同分辨率和字号。
            if abs(item.center_y - avg_y) <= max(12.0, avg_height * 0.65):
                matched_row = row
                break
        if matched_row is None:
            rows.append([item])
        else:
            matched_row.append(item)

    for row in rows:
        # 行内从左到右排序，后续 label-value 配对依赖这个顺序。
        row.sort(key=lambda item: item.box[0])
    return rows


def _extract_from_rows(field_name: str, rows: list[list[OcrItem]]) -> FieldResult | None:
    """从行结构中抽取 label-value 字段。

    典型页面布局：

    - 同一行：`号码：` 在左，`13800001234复制` 在右。
    - 相邻行：label 单独占一行，value 在下一行。
    """
    aliases = FIELD_ALIASES[field_name]
    for row_index, row in enumerate(rows):
        for item_index, item in enumerate(row):
            if not _looks_like_label(item.text, aliases):
                continue

            # 优先取同一行 label 右侧的文本。如果 OCR 将 value 放到下一行，再取下一行。
            candidates = row[item_index + 1 :]
            if not candidates and row_index + 1 < len(rows):
                candidates = rows[row_index + 1]

            # 过滤掉其他 label，避免类似 `客户名称：` 被拼进 value。
            value_items = [
                candidate
                for candidate in candidates
                if not _is_any_label(candidate.text) and candidate.text != item.text
            ]
            if not value_items:
                continue

            value = _normalize_field_value(field_name, _join_value_items(value_items))
            # label 和 value 任何一侧置信度低都应拉低整体置信度。
            confidence = min(item.score, sum(value.score for value in value_items) / len(value_items))
            return FieldResult(
                value=value,
                confidence=confidence,
                box=_merge_boxes(value_items),
                source="label_value",
                candidates=(value,),
            )
    return None


def _extract_inline_label_value(field_name: str, items: list[OcrItem]) -> FieldResult | None:
    """抽取单个 OCR item 内的 `label：value`。

    PaddleOCR 有时会把整行文本识别成一个 item，例如：
    `套餐名称：全月-广东流量王白银畅享220-预存200`。
    这种情况下无法依靠行内右侧 item，因此先拆 inline 文本。
    """
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
    """从 inline 文本中拆出 value。

    当前支持：
    - `别名：值`
    - `别名:值`
    - `别名 值`
    """
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
    """使用正则做字段兜底抽取。

    正则抽取没有明确 label 上下文，容易误命中，因此只在 label-value 策略失败后使用。
    """
    joined = " ".join(item.text for item in items)
    if field_name == "号码":
        match = PHONE_RE.search(joined)
        if match:
            return FieldResult(match.group(0), 0.75, None, "pattern", (match.group(0),))
    if field_name == "日期":
        # 优先订单时间戳，避免先命中页面顶部的 `2026.06.04-2026.06.11` 筛选区间。
        match = TIMESTAMP_RE.search(joined)
        if match:
            value = _normalize_timestamp(match.group(0))
            return FieldResult(value, 0.85, None, "timestamp_pattern", (value,))
        match = DATE_RE.search(joined)
        if match:
            return FieldResult(match.group(0), 0.75, None, "pattern", (match.group(0),))
    return None


def _extract_phone_from_filename(image_path: Path) -> FieldResult | None:
    """从文件名中兜底提取手机号。

    当前验证集文件名包含手机号，所以这个兜底对快速验证有帮助。
    生产环境上传文件名通常不可信，因此该来源置信度固定较低。
    """
    match = PHONE_RE.search(image_path.stem)
    if not match:
        return None
    phone = match.group(0)
    return FieldResult(phone, 0.5, None, "filename", (phone,))


def _normalize_timestamp(value: str) -> str:
    """规整时间戳格式。

    OCR 有时会把日期和时间粘在一起，例如 `2026.06.1115:46:45`。
    这里只补中间空格，不改变日期分隔符，避免过度格式化引入歧义。
    """
    compact = re.sub(r"\s+", " ", value).strip()
    return re.sub(
        r"^(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)(\d{1,2}:\d{2}:\d{2})$",
        r"\1 \2",
        compact,
    )


def _normalize_field_value(field_name: str, value: str) -> str:
    """按字段类型清洗 value。

    第一阶段只做低风险清洗：
    - 号码：从 `13800001234复制` 中提取手机号。
    - 日期：补齐日期和时间之间的空格。
    - 其他字段：只去除首尾空白。
    """
    cleaned = value.strip()
    if field_name == "号码":
        match = PHONE_RE.search(cleaned)
        if match:
            return match.group(0)
    if field_name == "日期":
        return _normalize_timestamp(cleaned)
    return cleaned


def _looks_like_label(text: str, aliases: tuple[str, ...]) -> bool:
    """判断文本是否是某个字段的 label。

    使用精确匹配而不是包含匹配，是为了避免 value 文本中出现 `套餐`、`时间`
    等词时被误判为 label。
    """
    normalized = _normalize_label(text)
    return normalized in {_normalize_label(alias) for alias in aliases}


def _is_any_label(text: str) -> bool:
    """判断文本是否属于任意目标字段的 label。"""
    return any(_looks_like_label(text, aliases) for aliases in FIELD_ALIASES.values())


def _normalize_label(text: str) -> str:
    """归一化 label 文本，消除 OCR 中常见的标点和空白差异。"""
    return re.sub(r"[\s:：|｜\-_]", "", text)


def _join_value_items(items: list[OcrItem]) -> str:
    """拼接同一字段的多个 value 文本片段。"""
    return "".join(item.text.strip() for item in items if item.text.strip())


def _merge_boxes(items: list[OcrItem]) -> tuple[float, float, float, float]:
    """合并多个 OCR 文本框，用于前端高亮字段值区域。"""
    return (
        min(item.box[0] for item in items),
        min(item.box[1] for item in items),
        max(item.box[2] for item in items),
        max(item.box[3] for item in items),
    )

"""PaddleOCR 输出归一化。

PaddleOCR 3.x 的 Python API 返回对象在不同调用方式下可能是 dict，也可能是
带 `json` / `res` 属性的结果对象。业务字段抽取如果直接依赖这些外部结构，
后续升级 PaddleOCR 时会很脆。

本模块把外部 OCR 结果收敛为项目内部稳定结构 `OcrItem`，后续布局重建、
字段抽取和 JSON 输出都只依赖这个结构。
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OcrItem:
    """项目内部统一的 OCR 文本项。

    Attributes:
        text: OCR 识别出的文本。
        score: OCR 识别置信度。
        box: 文本区域外接矩形 `(x1, y1, x2, y2)`。
    """

    text: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def center_y(self) -> float:
        """文本框中心 y 坐标，用于按行聚类。"""
        return (self.box[1] + self.box[3]) / 2

    @property
    def center_x(self) -> float:
        """文本框中心 x 坐标，预留给后续更精细的布局判断。"""
        return (self.box[0] + self.box[2]) / 2

    @property
    def height(self) -> float:
        """文本框高度。

        最小值设为 1.0，避免异常空框导致后续行聚类阈值为 0。
        """
        return max(1.0, self.box[3] - self.box[1])

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 JSON 的结构。"""
        return {
            "text": self.text,
            "score": self.score,
            "box": [round(value, 2) for value in self.box],
        }


def normalize_paddle_result(raw_result: Any) -> list[OcrItem]:
    """将 PaddleOCR 3.x 单个结果对象转换为 `OcrItem` 列表。"""
    data = _to_mapping(raw_result)
    res = data.get("res", data)

    # PaddleOCR pipeline 输出通常使用 rec_* 字段；部分模块输出可能使用 dt_*。
    # 这里兼容两类命名，避免字段抽取层感知 OCR 框架细节。
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
    """把 PaddleOCR 结果对象尽量转换为 dict。

    这里按常见形态逐个尝试：
    1. 已经是 dict。
    2. 对象有 `json` 属性。
    3. 对象有 `res` 属性。
    4. 普通 Python 对象的 `__dict__`。
    """
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
    """将 OCR polygon 转成外接矩形。

    PaddleOCR 常返回四点坐标。字段抽取当前只需要粗粒度空间关系，
    所以使用外接矩形即可。后续如果要精确高亮倾斜文本，可在报告中
    额外保留原始 polygon。
    """
    if poly is None:
        return (0.0, 0.0, 0.0, 0.0)

    points = list(poly)
    if len(points) == 4 and all(isinstance(value, (int, float)) for value in points):
        x1, y1, x2, y2 = [float(value) for value in points]
        return (x1, y1, x2, y2)

    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (min(xs), min(ys), max(xs), max(ys))

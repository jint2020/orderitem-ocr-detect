from __future__ import annotations

"""第一阶段 OCR 验证 CLI。

这个模块把当前阶段的“快速验证”流程串起来：

1. 从本地目录发现验证图片。
2. 使用本地 PP-OCRv6 检测模型和识别模型构建 PaddleOCR pipeline。
3. 对每张图片执行 EXIF 归一化和必要时的多角度 OCR。
4. 将 PaddleOCR 输出归一化为项目内部的 `OcrItem`。
5. 按当前规则抽取 `号码`、`日期`、`姓名`、`套餐信息`。
6. 用字段质量评分选择最佳方向候选。
7. 写出单图 JSON 报告、汇总 JSON 报告和可读运行日志。

当前模块定位是验证工具，不是生产 HTTP 服务。这里保留 `ocr` 注入参数，是为了
单元测试能用轻量 fake OCR 覆盖流程和日志，而不必每次都加载 PaddleOCR 大模型。
"""

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, TextIO

import yaml

from unicom_ocr_detect.field_quality import apply_quality_to_fields, evaluate_fields
from unicom_ocr_detect.fields import extract_fields
from unicom_ocr_detect.images import discover_images, iter_orientation_images
from unicom_ocr_detect.ocr_result import normalize_paddle_result
from unicom_ocr_detect.visualization import save_label_image


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    默认参数都指向当前项目的第一阶段验证目录，方便直接执行：
    `uv run ocr-validate`。
    """
    parser = argparse.ArgumentParser(description="Run first-phase OCR validation.")
    parser.add_argument("--images", type=Path, default=Path("data/validation"))
    parser.add_argument("--det-model-dir", type=Path, default=Path("models/PP-OCRv6_small_det_infer"))
    parser.add_argument("--rec-model-dir", type=Path, default=Path("models/PP-OCRv6_medium_rec"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/validation"))
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> int:
    """CLI 入口。

    返回 int 是为了后续扩展为更明确的退出码；当前成功固定返回 0。
    """
    args = build_parser().parse_args()
    run_validation(
        images_dir=args.images,
        det_model_dir=args.det_model_dir,
        rec_model_dir=args.rec_model_dir,
        output_dir=args.output_dir,
        limit=args.limit,
    )
    return 0


def run_validation(
    images_dir: Path,
    det_model_dir: Path,
    rec_model_dir: Path,
    output_dir: Path,
    limit: int | None = None,
    ocr: Any | None = None,
    log_stream: TextIO | None = None,
) -> dict[str, Any]:
    """执行完整 OCR 快速验证并返回汇总结果。

    Args:
        images_dir: 验证图片目录。
        det_model_dir: 文本检测模型目录。
        rec_model_dir: 文本识别模型目录。
        output_dir: JSON 报告输出目录。
        limit: 只处理前 N 张图片，用于 smoke test。
        ocr: 可注入的 OCR 对象。生产运行传 None，由本函数加载 PaddleOCR。
        log_stream: 日志输出流，默认 stdout；测试中可捕获。

    Returns:
        汇总统计，内容与 `outputs/validation/summary.json` 一致。
    """
    log_stream = log_stream or sys.stdout
    images = discover_images(images_dir)
    if limit is not None:
        images = images[:limit]
    if not images:
        raise ValueError(f"No validation images found in {images_dir}")

    if not det_model_dir.exists():
        raise FileNotFoundError(f"Text detection model directory does not exist: {det_model_dir}")
    if not rec_model_dir.exists():
        raise FileNotFoundError(f"Text recognition model directory does not exist: {rec_model_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    label_image_dir = output_dir / "label_img"
    label_image_dir.mkdir(parents=True, exist_ok=True)
    _log(
        log_stream,
        f"start images={len(images)} input_dir={images_dir} output_dir={output_dir}",
    )
    _log(log_stream, f"model det_dir={det_model_dir} rec_dir={rec_model_dir} device=cpu")
    if ocr is None:
        ocr = _build_paddleocr(det_model_dir, rec_model_dir)

    started_at = time.time()
    image_reports: list[dict[str, Any]] = []
    for index, image_path in enumerate(images, start=1):
        _log(log_stream, f"image start {index}/{len(images)} {image_path.name}")
        image_start = time.time()

        candidate = _select_orientation_candidate(ocr, image_path, log_stream)
        ocr_items = candidate["ocr_items"]
        fields = candidate["fields"]
        label_image_path = label_image_dir / image_path.name
        save_label_image(
            image_path,
            ocr_items,
            fields,
            label_image_path,
            rotation_degrees=candidate["rotation_degrees"],
        )
        report = {
            "image": str(image_path),
            "elapsed_seconds": round(time.time() - image_start, 4),
            "selected_rotation_degrees": candidate["rotation_degrees"],
            "field_quality": candidate["quality"].to_dict(),
            "orientation_candidates": [
                _candidate_summary(candidate_report)
                for candidate_report in candidate["orientation_candidates"]
            ],
            "label_image": str(label_image_path),
            "fields": {name: result.to_dict() for name, result in fields.items()},
            "raw_ocr": [item.to_dict() for item in ocr_items],
        }
        image_reports.append(report)

        report_path = output_dir / f"{image_path.stem}.json"
        # 单图报告保留 raw_ocr，便于排查“模型没识别出来”还是“字段规则没抽出来”。
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        populated = sum(1 for result in fields.values() if result.value)
        confirm = sum(1 for result in fields.values() if result.need_confirm)
        _log(
            log_stream,
            (
                f"image done {index}/{len(images)} {image_path.name} "
                f"elapsed={report['elapsed_seconds']}s ocr_items={len(ocr_items)} "
                f"populated={populated}/4 need_confirm={confirm}/4"
            ),
        )
        _log(log_stream, f"report written {report_path}")
        _log(log_stream, f"label image written {label_image_path}")

    summary = _build_summary(image_reports, time.time() - started_at)
    summary_path = output_dir / "summary.json"
    # 汇总报告只统计当前可自动判断的事实：字段是否填充、是否需要确认。
    # 没有人工真值文件前，不在这里声称字段准确率。
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _log(
        log_stream,
        (
            f"summary images={summary['image_count']} "
            f"elapsed={summary['elapsed_seconds']}s "
            f"avg={summary['avg_seconds_per_image']}s "
            f"populated={summary['field_populated_count']} "
            f"need_confirm={summary['field_need_confirm_count']}"
        ),
    )
    _log(log_stream, f"summary written {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2), file=log_stream)
    return summary


def _select_orientation_candidate(
    ocr: Any,
    image_path: Path,
    log_stream: TextIO,
) -> dict[str, Any]:
    """选择最可信的图片方向候选。

    为控制 CPU 成本，先跑 EXIF 归一化后的 0 度候选。如果字段质量已经可接受，
    就不再尝试其他角度。当 0 度质量不达标时，再尝试 90/180/270 度，
    并用字段质量分选择最终结果。
    """
    candidates: list[dict[str, Any]] = []
    for rotation, candidate_path in iter_orientation_images(image_path):
        candidate_started_at = time.time()
        raw_results = ocr.predict(str(candidate_path))
        ocr_items = []
        for raw_result in raw_results:
            ocr_items.extend(normalize_paddle_result(raw_result))

        raw_fields = extract_fields(ocr_items, image_path=image_path)
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
        _log(
            log_stream,
            (
                f"orientation candidate rotation={rotation} "
                f"score={quality.score:.4f} acceptable={quality.acceptable} "
                f"valid={quality.valid_fields}"
            ),
        )

        if rotation == 0 and quality.acceptable:
            break

    selected = max(
        candidates,
        key=lambda item: (
            item["quality"].score,
            -_rotation_cost(item["rotation_degrees"]),
        ),
    )
    selected["orientation_candidates"] = candidates
    _log(
        log_stream,
        (
            f"orientation selected rotation={selected['rotation_degrees']} "
            f"score={selected['quality'].score:.4f} acceptable={selected['quality'].acceptable}"
        ),
    )
    return selected


def _rotation_cost(rotation: int) -> int:
    """同分时优先选择原图，其次选择旋转角度更小的候选。"""
    return min(rotation % 360, (-rotation) % 360)


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    """压缩候选报告，避免单图 JSON 重复写入多份 raw OCR。"""
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


def _build_paddleocr(det_model_dir: Path, rec_model_dir: Path):
    """使用本地模型目录构建 PaddleOCR pipeline。

    PaddleOCR 会校验 `*_model_name` 与模型目录中的 `inference.yml` 是否一致。
    因此这里不写死模型名，而是从每个模型目录读取 `Global.model_name`。
    """
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
    """从 PaddleOCR 推理模型目录读取模型名。

    本地模型目录至少应包含 `inference.yml`，其中 `Global.model_name`
    是 PaddleOCR 3.x pipeline 初始化时需要的模型标识。
    """
    config_path = model_dir / "inference.yml"
    if not config_path.exists():
        raise FileNotFoundError(f"Model config does not exist: {config_path}")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    model_name = config.get("Global", {}).get("model_name")
    if not model_name:
        raise ValueError(f"Global.model_name missing in {config_path}")
    return str(model_name)


def _log(stream: TextIO, message: str) -> None:
    """输出统一前缀的验证日志。

    使用固定前缀便于 `grep` 或日志平台过滤，也方便和 PaddleOCR 自身日志区分。
    """
    print(f"[ocr-validate] {message}", file=stream, flush=True)


def _build_summary(
    image_reports: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """根据单图报告生成当前阶段的汇总统计。

    `field_populated_count` 表示字段有值，不代表字段正确。
    `field_need_confirm_count` 表示字段置信度低于确认阈值，需要前端重点提示。
    """
    field_names = ("号码", "日期", "姓名", "套餐信息")
    populated = {
        field_name: sum(1 for report in image_reports if report["fields"][field_name]["value"])
        for field_name in field_names
    }
    needs_confirm = {
        field_name: sum(1 for report in image_reports if report["fields"][field_name]["need_confirm"])
        for field_name in field_names
    }

    return {
        "image_count": len(image_reports),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "avg_seconds_per_image": round(elapsed_seconds / len(image_reports), 4),
        "field_populated_count": populated,
        "field_need_confirm_count": needs_confirm,
        "outputs": [f"{Path(report['image']).stem}.json" for report in image_reports],
    }


if __name__ == "__main__":
    raise SystemExit(main())

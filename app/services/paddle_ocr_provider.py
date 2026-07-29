"""Lazy PaddleOCR provider wrapper for OCR services."""

from pathlib import Path
from typing import Any, Protocol

import yaml


class OcrProvider(Protocol):
    def predict(self, image_path: Path, use_classifier: bool = False) -> list[Any]: ...


class PaddleOcrProvider:
    """Holds two lazy PaddleOCR instances: a plain 0° pass and a classifier pass.

    The hybrid OCR service tries the plain pass first (no orientation classifier,
    fastest path for upright images) and only falls back to the classifier pass
    when the plain result fails business-quality checks. Keeping both instances
    lazy avoids paying the classification overhead for the common upright case.
    """

    def __init__(
        self,
        det_model_dir: Path,
        rec_model_dir: Path,
        doc_orientation_model_dir: Path,
        enable_mkldnn: bool = False,
        cpu_threads: int | None = None,
        det_limit_side_len: int | None = None,
        det_limit_type: str | None = None,
        enable_new_ir: bool = True,
    ):
        self.det_model_dir = det_model_dir
        self.rec_model_dir = rec_model_dir
        self.doc_orientation_model_dir = doc_orientation_model_dir
        self.enable_mkldnn = enable_mkldnn
        self.cpu_threads = cpu_threads
        self.det_limit_side_len = det_limit_side_len
        self.det_limit_type = det_limit_type
        self.enable_new_ir = enable_new_ir
        self._ocr_plain: Any | None = None
        self._ocr_classifier: Any | None = None

    def predict(self, image_path: Path, use_classifier: bool = False) -> list[Any]:
        return self._get_ocr(use_classifier).predict(str(image_path))

    def _get_ocr(self, use_classifier: bool):
        if use_classifier:
            if self._ocr_classifier is None:
                self._ocr_classifier = build_paddleocr(
                    self.det_model_dir,
                    self.rec_model_dir,
                    self.doc_orientation_model_dir,
                    use_doc_orientation_classify=True,
                    enable_mkldnn=self.enable_mkldnn,
                    cpu_threads=self.cpu_threads,
                    det_limit_side_len=self.det_limit_side_len,
                    det_limit_type=self.det_limit_type,
                    enable_new_ir=self.enable_new_ir,
                )
            return self._ocr_classifier
        if self._ocr_plain is None:
            self._ocr_plain = build_paddleocr(
                self.det_model_dir,
                self.rec_model_dir,
                self.doc_orientation_model_dir,
                use_doc_orientation_classify=False,
                enable_mkldnn=self.enable_mkldnn,
                cpu_threads=self.cpu_threads,
                det_limit_side_len=self.det_limit_side_len,
                det_limit_type=self.det_limit_type,
                enable_new_ir=self.enable_new_ir,
            )
        return self._ocr_plain


def build_paddleocr(
    det_model_dir: Path,
    rec_model_dir: Path,
    doc_orientation_model_dir: Path,
    *,
    use_doc_orientation_classify: bool,
    enable_mkldnn: bool = False,
    cpu_threads: int | None = None,
    det_limit_side_len: int | None = None,
    det_limit_type: str | None = None,
    enable_new_ir: bool = True,
):
    from paddleocr import PaddleOCR

    # 方向分类器（PP-LCNet_x1_0_doc_ori）在 PaddleOCR 内部判定 0/90/180/270
    # 并把图旋正后再做一次 det+rec，替代原先 4 次全量 OCR 的多角度兜底。
    # 混合策略下默认走 plain（关分类器，0°），仅当 plain 不过质量门时才回退到分类器。
    kwargs: dict[str, Any] = dict(
        text_detection_model_name=read_model_name(det_model_dir),
        text_detection_model_dir=str(det_model_dir),
        text_recognition_model_name=read_model_name(rec_model_dir),
        text_recognition_model_dir=str(rec_model_dir),
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        # PaddleOCR 默认 enable_mkldnn=True；oneDNN 与 PP-OCRv6 在 paddlepaddle
        # 3.3.1 上不兼容，关闭后走通用 CPU 算子（run_mode="paddle"）。见 app/config.py。
        enable_mkldnn=enable_mkldnn,
    )
    if cpu_threads is not None:
        kwargs["cpu_threads"] = cpu_threads
    # 留空时沿用 PaddleOCR pipeline 配置（limit_side_len=64 / limit_type=min，
    # 大图几乎不缩小）。设成 960 / max 可显著降低检测耗时。见 app/config.py。
    if det_limit_side_len is not None:
        kwargs["text_det_limit_side_len"] = det_limit_side_len
    if det_limit_type is not None:
        kwargs["text_det_limit_type"] = det_limit_type
    if not enable_new_ir:
        # enable_new_ir 不是 PaddleOCR 的公开参数，只能经 engine_config 传到
        # paddle_static runner（runner.py 的 CPU 分支读 self._config["enable_new_ir"]）。
        # 注意 PaddleOCR 收到 engine_config 后会整个替换掉它自己按 enable_mkldnn /
        # cpu_threads 生成的配置（paddleocr/_common_args.py:117），所以这里必须把
        # run_mode 和 cpu_threads 一并写全，否则那两项会被静默丢弃。
        engine_config: dict[str, Any] = {
            "run_mode": "mkldnn" if enable_mkldnn else "paddle",
            "enable_new_ir": False,
            "cpu_threads": cpu_threads if cpu_threads is not None else 10,
        }
        if enable_mkldnn:
            engine_config["mkldnn_cache_capacity"] = 10
        kwargs["engine_config"] = {"paddle_static": engine_config}
    if use_doc_orientation_classify:
        kwargs.update(
            doc_orientation_classify_model_name=read_model_name(doc_orientation_model_dir),
            doc_orientation_classify_model_dir=str(doc_orientation_model_dir),
            use_doc_orientation_classify=True,
        )
    else:
        kwargs["use_doc_orientation_classify"] = False
    return PaddleOCR(**kwargs)


def read_model_name(model_dir: Path) -> str:
    config_path = model_dir / "inference.yml"
    if not config_path.exists():
        raise FileNotFoundError(f"Model config does not exist: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    model_name = config.get("Global", {}).get("model_name")
    if not model_name:
        raise ValueError(f"Global.model_name missing in {config_path}")
    return str(model_name)

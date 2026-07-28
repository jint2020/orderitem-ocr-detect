import os
from pathlib import Path

DETECTION_MODEL_DIR = Path(os.environ.get("DETECTION_MODEL_DIR", "models/PP-OCRv6_small_det_infer"))
RECOGNITION_MODEL_DIR = Path(os.environ.get("RECOGNITION_MODEL_DIR", "models/PP-OCRv6_medium_rec"))
DOC_ORIENTATION_MODEL_DIR = Path(
    os.environ.get("DOC_ORIENTATION_MODEL_DIR", "models/PP-LCNet_x1_0_doc_ori")
)
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))

# PaddleOCR 在 CPU 上默认启用 oneDNN(MKLDNN)。paddlepaddle 3.3.1 的 oneDNN + PIR
# 执行器加载 PP-OCRv6 检测模型时会抛
#   NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
#   [pir::ArrayAttribute<pir::DoubleAttribute>]
# 因此默认关闭，退回通用 CPU 算子。设 ENABLE_MKLDNN=true 可在不受影响的环境上重新开启。
ENABLE_MKLDNN = os.environ.get("ENABLE_MKLDNN", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
OCR_PROVIDER_FACTORY = None

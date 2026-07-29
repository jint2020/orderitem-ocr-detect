import os
from pathlib import Path

DETECTION_MODEL_DIR = Path(os.environ.get("DETECTION_MODEL_DIR", "models/PP-OCRv6_small_det_infer"))
RECOGNITION_MODEL_DIR = Path(os.environ.get("RECOGNITION_MODEL_DIR", "models/PP-OCRv6_medium_rec"))
DOC_ORIENTATION_MODEL_DIR = Path(
    os.environ.get("DOC_ORIENTATION_MODEL_DIR", "models/PP-LCNet_x1_0_doc_ori")
)
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))

# 推理后端。
# - "paddle"（默认）：paddlepaddle 自带后端。因 oneDNN 不可用（见 ENABLE_MKLDNN），
#   实际走的是未加速的通用 CPU 算子。
# - "onnxruntime"：改用 ONNX Runtime，绕开 paddle 后端。需要每个模型目录里除
#   inference.yml 外还有 inference.onnx，转换步骤见 models/README.md。
SUPPORTED_INFERENCE_ENGINES = ("paddle", "onnxruntime")
INFERENCE_ENGINE = os.environ.get("INFERENCE_ENGINE", "paddle").strip().lower()
if INFERENCE_ENGINE not in SUPPORTED_INFERENCE_ENGINES:
    raise ValueError(
        f"Unsupported INFERENCE_ENGINE: {INFERENCE_ENGINE!r}. "
        f"Supported values are: {', '.join(SUPPORTED_INFERENCE_ENGINES)}."
    )

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

# PIR 开关。
#
# 已实测：ENABLE_MKLDNN=true + ENABLE_NEW_IR=false 仍然抛同一个
# NotImplementedError，**不能**用来恢复 oneDNN。原因是 paddlex 的
# runners/paddle_static/runner.py 在关掉 PIR 之后仍然无条件调用
# config.enable_new_executor()，而崩溃正发生在新执行器的 oneDNN 指令路径
# （new_executor/instruction/onednn/onednn_instruction.cc:116），没有配置项能关掉它。
#
# 该开关保留仅为便于在其他 paddle 版本上复测，默认 true 与 paddle 自身默认一致。
ENABLE_NEW_IR = os.environ.get("ENABLE_NEW_IR", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# PaddleOCR 默认 cpu_threads=10，与 gunicorn 多 worker 叠加后会严重超额订阅 CPU。
# 默认取 核数/2，配合默认的 2 个 worker 恰好用满核数。改 GUNICORN_WORKERS 时
# 应同步调整，使 GUNICORN_WORKERS × CPU_THREADS ≈ 核数。
CPU_THREADS = int(os.environ.get("CPU_THREADS") or max(1, (os.cpu_count() or 4) // 2))

# 检测模型输入的缩放上限。PaddleOCR 的 OCR pipeline 配置为 limit_side_len=64 /
# limit_type=min，即大图几乎不缩小，高分辨率照片的检测耗时会非常高；而 paddlex 按
# 模型名给 PP-OCRv6_*_det 的默认值是 960 / max（长边缩到 960）。
# 留空保持 PaddleOCR 行为；设成 960 + max 可大幅提速，代价是小字可能漏检。
TEXT_DET_LIMIT_SIDE_LEN = int(os.environ["TEXT_DET_LIMIT_SIDE_LEN"]) if os.environ.get(
    "TEXT_DET_LIMIT_SIDE_LEN"
) else None
TEXT_DET_LIMIT_TYPE = os.environ.get("TEXT_DET_LIMIT_TYPE") or None
OCR_PROVIDER_FACTORY = None

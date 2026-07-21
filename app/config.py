import os
from pathlib import Path

DETECTION_MODEL_DIR = Path(os.environ.get("DETECTION_MODEL_DIR", "models/PP-OCRv6_small_det_infer"))
RECOGNITION_MODEL_DIR = Path(os.environ.get("RECOGNITION_MODEL_DIR", "models/PP-OCRv6_medium_rec"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))
OCR_PROVIDER_FACTORY = None

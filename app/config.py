from pathlib import Path

DETECTION_MODEL_DIR = Path("models/PP-OCRv6_small_det_infer")
RECOGNITION_MODEL_DIR = Path("models/PP-OCRv6_medium_rec")
OUTPUT_ROOT = Path("outputs/requests")
MAX_CONTENT_LENGTH = 20 * 1024 * 1024
OCR_PROVIDER_FACTORY = None
OCR_RESULT_REPOSITORY_FACTORY = None

from PIL import UnidentifiedImageError
from flask import Blueprint, current_app, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.schemas.ocr_schema import build_openapi_schema
from app.services.image_service import validate_upload_image
from app.services.ocr_service import OcrPersistenceError, OcrProcessingError, OcrService
from app.views.json_response import error, success

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@api_v1.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_exc):
    return error(413, "image is too large", 413)


@api_v1.get("/openapi.json")
def openapi():
    return success(build_openapi_schema())


@api_v1.post("/ocr/orders")
def recognize_order():
    if "image" not in request.files:
        return error(400, "image is required", 400)

    image = request.files["image"]
    valid, message = validate_upload_image(image)
    if not valid:
        return error(400, message, 400)

    try:
        service = OcrService(
            repository=current_app.extensions["ocr_repository"],
            provider=current_app.extensions["ocr_provider"],
        )
        content = service.recognize_order_image(image)
    except UnidentifiedImageError:
        return error(400, "invalid image file", 400)
    except OcrPersistenceError:
        return error(500, "failed to persist ocr result", 500)
    except OcrProcessingError as exc:
        if _caused_by(exc, UnidentifiedImageError):
            return error(400, "invalid image file", 400)
        if _caused_by(exc, (FileNotFoundError, ValueError)):
            return error(500, "ocr model is unavailable", 500)
        return error(500, "ocr processing failed", 500)
    except (FileNotFoundError, ValueError):
        return error(500, "ocr model is unavailable", 500)
    return success(content)


def _caused_by(exc: BaseException, expected: type[BaseException] | tuple[type[BaseException], ...]) -> bool:
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, expected):
            return True
        cause = cause.__cause__
    return False

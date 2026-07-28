from flask import Flask
from werkzeug.exceptions import RequestEntityTooLarge

from app.services.paddle_ocr_provider import PaddleOcrProvider


def create_app(config_object: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object("app.config")
    if config_object:
        app.config.update(config_object)

    app.extensions["ocr_provider"] = _build_provider(app)

    from app.controllers.api.v1.ocr_controller import api_v1

    app.register_blueprint(api_v1)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_exc):
        from app.views.json_response import error

        return error(413, "image is too large", 413)

    return app


def _build_provider(app: Flask):
    factory = app.config.get("OCR_PROVIDER_FACTORY")
    if factory is not None:
        return factory(app)
    return PaddleOcrProvider(
        app.config["DETECTION_MODEL_DIR"],
        app.config["RECOGNITION_MODEL_DIR"],
        app.config["DOC_ORIENTATION_MODEL_DIR"],
        app.config["ENABLE_MKLDNN"],
        app.config["CPU_THREADS"],
        app.config["TEXT_DET_LIMIT_SIDE_LEN"],
        app.config["TEXT_DET_LIMIT_TYPE"],
    )

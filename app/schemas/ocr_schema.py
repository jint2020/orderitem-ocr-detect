SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def is_supported_image(filename: str) -> bool:
    return any(filename.lower().endswith(suffix) for suffix in SUPPORTED_IMAGE_SUFFIXES)


def build_openapi_schema() -> dict[str, object]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Unicom OCR API", "version": "1.0.0"},
        "paths": {
            "/api/v1/ocr/orders": {
                "post": {
                    "summary": "Recognize order fields from one uploaded image",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["image"],
                                    "properties": {"image": {"type": "string", "format": "binary"}},
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Wrapped OCR result"},
                        "400": {"description": "Wrapped request error"},
                        "413": {"description": "Wrapped upload size error"},
                        "500": {"description": "Wrapped server error"},
                    },
                }
            }
        },
    }

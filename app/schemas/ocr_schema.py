def build_openapi_schema() -> dict[str, object]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Unicom OCR API", "version": "1.0.0"},
        "paths": {
            "/api/v1/ocr/orders": {
                "post": {
                    "summary": "Recognize order fields from one uploaded image",
                    "parameters": [
                        {
                            "name": "label_image",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["true", "false"],
                                "default": "true",
                            },
                            "description": "Set to false to omit the base64 label image from the response.",
                        }
                    ],
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
                        "200": {
                            "description": "Wrapped OCR result with fields, field_quality, raw_ocr, selected_rotation_degrees, and label_image_base64 (omitted when label_image=false)"
                        },
                        "400": {"description": "Wrapped request error"},
                        "413": {"description": "Wrapped upload size error"},
                        "500": {"description": "Wrapped server error"},
                    },
                }
            }
        },
    }

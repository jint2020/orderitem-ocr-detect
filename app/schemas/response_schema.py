def wrap_success(content: dict[str, object]) -> dict[str, object]:
    return {"code": 0, "content": content, "message": ""}


def wrap_error(code: int, message: str) -> dict[str, object]:
    return {"code": code, "content": {}, "message": message}

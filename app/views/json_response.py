from flask import jsonify


def success(content: dict[str, object], status_code: int = 200):
    return jsonify({"code": 0, "content": content, "message": ""}), status_code


def error(code: int, message: str, status_code: int):
    return jsonify({"code": code, "content": {}, "message": message}), status_code

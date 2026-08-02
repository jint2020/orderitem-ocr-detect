"""API key authentication for the v1 API."""

import hmac

from flask import current_app, request

from app.views.json_response import error

# openapi.json 只返回静态 schema，不含任何业务数据，且被 docker-compose 的
# healthcheck 使用；对它鉴权会让健康检查失败，故豁免。
EXEMPT_ENDPOINTS = frozenset({"api_v1.openapi"})

API_KEY_HEADER = "X-API-Key"


def verify_api_key():
    """Blueprint ``before_request`` hook.

    Returns ``None`` to let the request through, or a wrapped 401 response.
    Authentication is disabled when no key is configured, so local development
    and the test suite work without extra setup.
    """
    configured = current_app.config.get("API_KEYS") or ()
    if not configured:
        return None
    if request.endpoint in EXEMPT_ENDPOINTS:
        return None

    provided = request.headers.get(API_KEY_HEADER, "")
    # compare_digest 而非 ==：避免按字符逐位比较带来的时序侧信道。
    if not any(hmac.compare_digest(provided, key) for key in configured):
        return error(401, "invalid or missing api key", 401)
    return None

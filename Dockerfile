# 无状态 OCR API 容器。
# - 强制 linux/amd64：PaddlePaddle 只发布 linux x86_64 wheel（无 aarch64）。
#   Apple Silicon 上由 Docker Desktop 经 Rosetta 模拟运行。
# - 模型不打包进镜像，通过 docker-compose 只读挂载到 /app/models。
# - 不需要 outputs 卷：服务无状态，每请求在临时目录里处理。

FROM --platform=linux/amd64 python:3.12-slim

# 可选加速：国内构建时把 apt / pip 换成镜像源。默认空值 = 走官方源，行为不变。
# 例：APT_MIRROR_HOST=mirrors.tencentyun.com（腾讯云内网）
#     PIP_INDEX_URL=https://mirrors.tencentyun.com/pypi/simple
ARG APT_MIRROR_HOST=""
ARG PIP_INDEX_URL="https://pypi.org/simple"

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_DEFAULT_INDEX=${PIP_INDEX_URL} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

# PaddlePaddle / PaddleOCR / OpenCV 运行所需的系统库
# Debian 13 (trixie) 使用 deb822 格式的 /etc/apt/sources.list.d/debian.sources
RUN if [ -n "$APT_MIRROR_HOST" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR_HOST|g; s|security.debian.org|$APT_MIRROR_HOST|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libx11-6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.12

WORKDIR /app

# 先装依赖（利用层缓存：仅 pyproject/uv.lock 变化才重装）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev \
    && uv pip install gunicorn==23.0.0

# 应用代码
COPY app ./app

ENV FLASK_APP=app \
    GUNICORN_WORKERS=2

EXPOSE 5000

# gunicorn 启动；worker 数可通过 GUNICORN_WORKERS 覆盖。
# 每个 worker 会在首次 OCR 请求时懒加载 PaddleOCR 模型（内存与 worker 数成正比）。
CMD ["sh", "-c", "gunicorn --workers ${GUNICORN_WORKERS:-2} --threads 2 --timeout 300 --bind 0.0.0.0:5000 'app:create_app()'"]

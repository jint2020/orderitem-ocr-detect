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
ARG PYPI_FILES_BASE=""

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

# 这一层要下约 400 MB（paddlepaddle 186 MB、opencv-contrib-python 143 MB 等）。
# uv.lock 锁定的是 files.pythonhosted.org 的绝对 URL，`uv sync --frozen` 按 URL
# 直接下载，PIP_INDEX_URL / UV_DEFAULT_INDEX 对它无效，必须改写主机名才能走镜像源。
# 只换主机名不动 sha256，uv 仍会校验哈希，镜像内容不一致会直接构建失败。
RUN if [ -n "$PYPI_FILES_BASE" ]; then \
        sed -i "s|https://files.pythonhosted.org|$PYPI_FILES_BASE|g" uv.lock; \
    fi \
    && uv sync --frozen --no-install-project --no-dev \
    && uv pip install gunicorn==23.0.0

# 应用代码
COPY app ./app

ENV FLASK_APP=app \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=1

EXPOSE 5000

# gunicorn 启动；worker 数与每 worker 线程数均可通过环境变量覆盖。
# 每个 worker 会在首次 OCR 请求时懒加载 PaddleOCR 模型（内存与 worker 数成正比）。
#
# 并发 OCR 数 = GUNICORN_WORKERS × GUNICORN_THREADS，每个 OCR 又会用
# CPU_THREADS 个算子线程，三者相乘才是真实的线程压力：
#     GUNICORN_WORKERS × GUNICORN_THREADS × CPU_THREADS ≈ CPU 核数
# OCR 是 CPU 密集型，线程默认 1（排队优于超额订阅）。
CMD ["sh", "-c", "gunicorn --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-1} --timeout 300 --bind 0.0.0.0:5000 'app:create_app()'"]

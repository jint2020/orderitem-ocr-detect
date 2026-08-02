# Ubuntu Server 24.04 LTS (x86_64) Docker Compose 部署指南

本服务是无状态的 Flask JSON API，容器内用 gunicorn 运行，模型以只读方式从宿主机挂载。
本文假设服务器已装好 Docker Engine 与 Compose 插件。

## 0. 环境确认

```bash
uname -m                    # 期望 x86_64（PaddlePaddle 只发布 x86_64 Linux wheel）
docker version
docker compose version      # 需要 Compose V2（docker compose，不是 docker-compose）
docker run --rm hello-world # 确认当前用户可用 docker（否则 sudo usermod -aG docker $USER 后重新登录）
```

资源建议（CPU 推理）：

| 项 | 建议 |
|---|---|
| CPU | ≥ 4 核 |
| 内存 | ≥ 4 GB（2 个 worker，每个 worker 最多懒加载 2 套 PaddleOCR 实例） |
| 磁盘 | ≥ 10 GB（镜像约 3–4 GB，主要是 paddlepaddle） |

## 1. 获取代码

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs
git clone <仓库地址> ~/orderitem-ocr-detect
cd ~/orderitem-ocr-detect
```

## 2. 下载模型

模型不打包进镜像，必须先下载到宿主机 `models/` 目录（详见 `models/README.md`）。

注意检测模型的 modelscope 仓库名是 `PP-OCRv6_small_det`，而配置默认的本地目录名带 `_infer` 后缀，clone 后需要改名：

```bash
cd models
git lfs install

git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_small_det.git
mv PP-OCRv6_small_det PP-OCRv6_small_det_infer

git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_medium_rec.git
git clone https://www.modelscope.cn/PaddlePaddle/PP-LCNet_x1_0_doc_ori.git
cd ..

# 校验：三个 inference.yml 都要存在
ls models/PP-OCRv6_small_det_infer/inference.yml \
   models/PP-OCRv6_medium_rec/inference.yml \
   models/PP-LCNet_x1_0_doc_ori/inference.yml
```

若权重文件只有几百字节，说明 lfs 未生效，进入对应目录执行 `git lfs pull`。

不想改目录名时，保留 `PP-OCRv6_small_det` 并在 `.env` 中设置
`DETECTION_MODEL_DIR=models/PP-OCRv6_small_det` 即可。

## 3. 配置

复制 `.env.example` 为 `.env` 并按需修改；不建 `.env` 也能跑，会使用默认值。

```bash
cp .env.example .env
```

| 变量 | 默认 | 说明 |
|---|---|---|
| `OCR_PORT` | `8080` | 宿主机端口，映射到容器 5000 |
| `GUNICORN_WORKERS` | `2` | worker 数，CPU 推理建议不超过 `核数 / 2` |
| `DETECTION_MODEL_DIR` | `models/PP-OCRv6_small_det_infer` | 检测模型目录（容器内相对 `/app`） |
| `RECOGNITION_MODEL_DIR` | `models/PP-OCRv6_medium_rec` | 识别模型目录 |
| `DOC_ORIENTATION_MODEL_DIR` | `models/PP-LCNet_x1_0_doc_ori` | 方向分类模型目录 |

## 4. 构建并启动

```bash
docker compose up --build -d
```

首次构建需要下载 paddlepaddle 等依赖，耗时较长（视网络 5–20 分钟）。

### 国内构建加速（强烈建议）

境内服务器直连 `deb.debian.org` 和 `pypi.org` 会非常慢：`apt-get update` 要拉近 10 MB 包索引，
依赖层要下约 400 MB wheel（paddlepaddle 186 MB、opencv-contrib-python 143 MB、pillow 45 MB 等）。

在 `.env` 中设置三个镜像源变量（腾讯云机器用内网源最快，免流量）：

```bash
APT_MIRROR_HOST=mirrors.tencentyun.com
PIP_INDEX_URL=https://mirrors.tencentyun.com/pypi/simple
PYPI_FILES_BASE=https://mirrors.tencentyun.com/pypi
```

三者分工不同，**必须一起设置**：

| 变量 | 作用的构建层 |
|---|---|
| `APT_MIRROR_HOST` | `apt-get update && apt-get install`（系统库） |
| `PIP_INDEX_URL` | `pip install uv`、`uv pip install gunicorn` |
| `PYPI_FILES_BASE` | `uv sync --frozen` —— 约 400 MB，构建耗时的大头 |

`PYPI_FILES_BASE` 单独存在是因为 `uv.lock` 锁定的是 `files.pythonhosted.org` 的**绝对 URL**，
`uv sync --frozen` 按 URL 直接下载，`PIP_INDEX_URL` / `UV_DEFAULT_INDEX` 对它无效，必须改写主机名。
改写只动主机名、不动 `sha256`，uv 仍会校验哈希，镜像内容不一致会直接构建失败。

其他镜像源见 `.env.example`（阿里云、清华）。设置后重新构建：

```bash
docker compose build && docker compose up -d
```

三个变量都留空则走官方源，行为与之前一致。

查看状态与日志：

```bash
docker compose ps           # STATUS 出现 (healthy) 表示健康检查通过
docker compose logs -f ocr
```

## 5. 验证

```bash
# 健康检查同款接口，不加载模型，应立即返回
curl -s http://127.0.0.1:8080/api/v1/openapi.json | head -c 200

# 真实识别（第一次请求会懒加载模型，可能耗时数十秒）
curl -X POST -F "image=@/path/to/order.jpg" \
  "http://127.0.0.1:8080/api/v1/ocr/orders?label_image=false"
```

返回 `{"code": 0, "content": {...}, "message": ""}` 即部署成功。

## 6. 对外开放端口

仅在需要从外部访问时开放；建议前面再挂一层 Nginx 做 TLS 与访问控制。

```bash
sudo ufw allow 8080/tcp
```

只想本机/内网访问时，可把 `docker-compose.yml` 的端口映射改为 `"127.0.0.1:${OCR_PORT:-8080}:5000"`。

## 6.0 开启 API Key 鉴权

接口返回真实号码与姓名，**公网暴露前必须开启鉴权**。

生成并配置：

```bash
cd ~/orderitem-ocr-detect
echo "API_KEYS=$(openssl rand -hex 32)" >> .env
docker compose up -d          # 改环境变量需 up -d，restart 不生效
grep API_KEYS .env            # 把 key 交给调用方
```

调用方通过请求头传递：

```bash
curl -X POST -H "X-API-Key: <key>" \
  -F "image=@order.jpg" \
  "https://ocr.example.com:8443/api/v1/ocr/orders?label_image=false"
```

验证鉴权确实生效——不带 key 应返回 401：

```bash
curl -s -X POST -F "image=@order.jpg" \
  "https://ocr.example.com:8443/api/v1/ocr/orders" | head -c 120
# {"code":401,"content":{},"message":"invalid or missing api key"}
```

说明：

- `API_KEYS` 支持逗号分隔配置多个，便于轮换：先加新 key，待调用方全部切换后再删旧 key。
- `GET /api/v1/openapi.json` 不鉴权——它只返回静态 schema，且被容器健康检查使用。
- 留空 `API_KEYS` 则完全不鉴权，仅适用于本地开发与内网隔离环境。

## 6.1 HTTPS（Nginx 反向代理 + Let's Encrypt）

### 前置条件

- 域名 A 记录已解析到本机公网 IP。
- **国内服务器需完成 ICP 备案**，否则 80/443 会被运营商拦截，Let's Encrypt 的 HTTP-01
  验证也无法通过。未备案时只能改用非标端口，或改用 DNS-01 验证。
- 安全组 / `ufw` 放通 80 与 443。

### 只让代理访问容器

反代到位后，容器端口不应再直接暴露到公网。在 `.env` 中设置：

```bash
OCR_BIND_HOST=127.0.0.1
```

```bash
docker compose up -d
sudo ufw delete allow 8080/tcp   # 如果之前放通过
```

### 安装并配置 Nginx

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo ufw allow 'Nginx Full'
```

`/etc/nginx/sites-available/ocr`（把 `ocr.example.com` 换成你的域名）：

```nginx
server {
    listen 80;
    server_name ocr.example.com;

    # 应用允许 20 MiB 上传，Nginx 默认只有 1m，不改会直接 413。
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8080;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 与 gunicorn 的 --timeout 300 对齐：每个 worker 的首个请求要懒加载模型，
        # 可能耗时数十秒，Nginx 默认 60s 会先超时。
        proxy_connect_timeout 30s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;
    }
}
```

启用并签发证书：

```bash
sudo ln -s /etc/nginx/sites-available/ocr /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d ocr.example.com
```

`certbot --nginx` 会自动补上 443 server 块、证书路径与 80→443 跳转，并注册续期定时器。

### 验证

```bash
curl -sI https://ocr.example.com/api/v1/openapi.json | head -3
curl -X POST -F "image=@data/test/xxx.jpg" \
  "https://ocr.example.com/api/v1/ocr/orders?label_image=false"

systemctl list-timers | grep certbot     # 自动续期已注册
sudo certbot renew --dry-run             # 演练续期
```

### 未备案时的替代方案：DNS-01 + 非标端口

境内服务器上，未备案域名会被云厂商拦截，表现为 certbot 报：

```
Type:   unauthorized
Detail: <IP>: Invalid response from https://dnspod.qcloud.com/static/webblock.html?d=<域名>
```

报错里的 IP 往往**不是你的服务器**，而是云厂商的拦截服务器——未备案域名的解析会被劫持过去。

绕开的办法是：用 DNS-01 验证签发证书（不需要 80 可达），Nginx 监听非标端口（不在
80/443 的拦截范围内）。**这只是技术上可行的临时方案，未备案域名在境内服务器提供
Web 服务本身不合规，正式对外仍需备案。** 且解析层面若被再次劫持，换端口也无济于事。

签发证书（手动 DNS 验证）：

```bash
sudo certbot certonly --manual --preferred-challenges dns -d ocr.example.com
```

按提示在 DNS 服务商处添加 TXT 记录。注意「主机记录」是**相对于域名的前缀**，
对 `ocr.example.com` 应填 `_acme-challenge.ocr`，填完整域名会变成
`_acme-challenge.ocr.example.com.example.com` 导致验证失败。

回车前先确认记录已生效：

```bash
dig +short TXT _acme-challenge.ocr.example.com @119.29.29.29
```

Nginx 配置（`listen` 端口改为 8443，其余同上）：

```nginx
server {
    listen 8443 ssl http2;
    server_name ocr.example.com;

    ssl_certificate     /etc/letsencrypt/live/ocr.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ocr.example.com/privkey.pem;

    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache         shared:SSL:10m;
    ssl_session_timeout       1d;
    ssl_session_tickets       off;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;
    }
}
```

几个要点：

- Ubuntu 24.04 自带 nginx 1.24，**不支持独立的 `http2 on;` 指令**（1.25.1 才引入），
  必须写成 `listen 8443 ssl http2;`。
- `certonly` 不会生成 `/etc/letsencrypt/options-ssl-nginx.conf` 与 `ssl-dhparams.pem`
  （那两个文件由 `--nginx` 安装器生成），因此 TLS 参数直接内联，避免 `include` 不存在的文件。
- 主机防火墙与**云厂商安全组**都要放通 8443，只放一处的表现是连接超时。
- `--manual` 签发的证书**无法自动续期**，90 天后需重复上述步骤。要自动化可安装
  DNS 插件（如 `certbot-dns-tencentcloud`）配合 API 密钥使用。

验证（必须从外网的机器上测，服务器本机走回环，验证不到公网链路）：

```bash
dig +short A ocr.example.com
nc -vz ocr.example.com 8443
curl -X POST -F "image=@<图片>.jpg" \
  "https://ocr.example.com:8443/api/v1/ocr/orders?label_image=false"
```

若要先确认 Nginx 本身无误、把问题范围缩小到 DNS 或安全组，在服务器上执行：

```bash
curl -sk --resolve ocr.example.com:8443:127.0.0.1 \
  "https://ocr.example.com:8443/api/v1/openapi.json" | head -c 200
```

### 可选：压缩 JSON 响应

带标注图时响应含 base64 JPEG，可达数 MB。在 server 块内加：

```nginx
    gzip on;
    gzip_types application/json;
    gzip_min_length 1024;
```

## 7. 日常运维

```bash
docker compose restart ocr           # 重启
docker compose down                  # 停止并移除容器
docker compose pull                  # 若改用远端镜像
git pull && docker compose up --build -d   # 更新代码并重建
docker compose logs --tail=200 ocr   # 查看最近日志
```

- 开机自启：compose 中已设置 `restart: unless-stopped`，Docker 服务自启即可（`sudo systemctl enable docker`）。
- 更新模型：直接替换宿主机 `models/` 下的目录后 `docker compose restart ocr`，无需重建镜像。
- 服务无状态，不产生需要持久化的数据卷；上传图片在临时目录处理，请求结束即删除。

## 8. 常见问题

**构建时 pip/apt 超时**：服务器出网受限时，为 Docker 配置代理（`/etc/systemd/system/docker.service.d/http-proxy.conf`）或使用内网镜像源。

**启动正常但识别报 500 `ocr model is unavailable`**：模型目录缺失或 `inference.yml` 不存在。容器内确认挂载：

```bash
docker compose exec ocr ls /app/models
```

注意检测模型目录名：modelscope 仓库叫 `PP-OCRv6_small_det`，而默认配置找的是
`PP-OCRv6_small_det_infer`，clone 后未改名就会报这个错。

**识别报 500 `ocr processing failed`**：OCR 执行阶段出错，原始异常未记入日志。手动复现拿堆栈：

```bash
docker compose cp <你的图片>.jpg ocr:/tmp/probe.jpg
docker compose exec -T ocr python -u - <<'PY'
import traceback
from pathlib import Path
from app.config import (
    DETECTION_MODEL_DIR, RECOGNITION_MODEL_DIR, DOC_ORIENTATION_MODEL_DIR, ENABLE_MKLDNN,
)
from app.services.paddle_ocr_provider import PaddleOcrProvider

prov = PaddleOcrProvider(
    DETECTION_MODEL_DIR, RECOGNITION_MODEL_DIR, DOC_ORIENTATION_MODEL_DIR, ENABLE_MKLDNN,
)
try:
    print('OK, results:', len(prov.predict(Path('/tmp/probe.jpg'), use_classifier=False)))
except Exception:
    traceback.print_exc()
PY
```

若堆栈是 `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]`，说明启用了 oneDNN —— paddlepaddle 3.3.1 的
oneDNN + PIR 执行器与 PP-OCRv6 检测模型不兼容。本项目默认已关闭（`ENABLE_MKLDNN=false`），
确认 `.env` 里没有把它设成 `true`。

**第一次请求很慢 / 504**：PaddleOCR 懒加载，首个请求包含模型初始化。gunicorn 超时已设为 300s；若前面挂了 Nginx，也要把 `proxy_read_timeout` 调大。

**单次识别耗时过长**：默认的 paddle 后端因 oneDNN 不可用（见 `ENABLE_MKLDNN`）只能走未加速的
通用 CPU 算子。4 核机器实测（1279×1706 图片，47 个文本框）：

| 配置 | 单次耗时 |
|---|---|
| paddle 后端（默认） | 21.3s |
| paddle + `CPU_THREADS=4` | 21.1s |
| paddle + 长边缩到 960 | 19.8s |
| **`INFERENCE_ENGINE=onnxruntime`** | **4.2s** |

调参手段合计只有约 8% 收益，换 ONNX Runtime 才是数量级的差别，且字段质量不变。
转换步骤见 `models/README.md`。

**并发下 CPU 打满、响应变慢**：OCR 是 CPU 密集型。降低 `GUNICORN_WORKERS`，或在 compose 的 `environment` 中限制线程数避免超额订阅：

```yaml
      OMP_NUM_THREADS: "2"
```

**内存不足被 OOM Kill**：每个 worker 独立加载模型，内存随 worker 数线性增长。先降到 `GUNICORN_WORKERS=1` 验证，再按内存余量上调。

**端口被占用**：改 `.env` 中的 `OCR_PORT` 后 `docker compose up -d`。

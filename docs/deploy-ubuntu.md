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

境内服务器直连 `deb.debian.org` 和 `pypi.org` 会非常慢，构建常卡在 `apt-get update`。
在 `.env` 中设置镜像源（腾讯云机器用内网源最快，免流量）：

```bash
APT_MIRROR_HOST=mirrors.tencentyun.com
PIP_INDEX_URL=https://mirrors.tencentyun.com/pypi/simple
```

阿里云用 `mirrors.cloud.aliyuncs.com`；非云厂商机器可用 `mirrors.tuna.tsinghua.edu.cn`
（pip 索引为 `https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`）。设置后重新构建：

```bash
docker compose build --no-cache && docker compose up -d
```

留空这两个变量则走官方源，行为与之前一致。

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

**第一次请求很慢 / 504**：PaddleOCR 懒加载，首个请求包含模型初始化。gunicorn 超时已设为 300s；若前面挂了 Nginx，也要把 `proxy_read_timeout` 调大。

**并发下 CPU 打满、响应变慢**：OCR 是 CPU 密集型。降低 `GUNICORN_WORKERS`，或在 compose 的 `environment` 中限制线程数避免超额订阅：

```yaml
      OMP_NUM_THREADS: "2"
```

**内存不足被 OOM Kill**：每个 worker 独立加载模型，内存随 worker 数线性增长。先降到 `GUNICORN_WORKERS=1` 验证，再按内存余量上调。

**端口被占用**：改 `.env` 中的 `OCR_PORT` 后 `docker compose up -d`。

# 模型下载 - modelscope

服务需要三个模型目录，缺一不可（方向分类模型只在 0° 结果未通过质量门时才懒加载，但生产环境必须提前准备好）。

**注意 modelscope 仓库名与本地目录名不一定相同**：`_infer` 是 PaddleX 推理包目录的后缀，不是仓库名。检测模型 clone 下来后需要改名。

| 用途 | modelscope 仓库 | 本地目录（配置默认值） | 配置项 |
|---|---|---|---|
| 文本检测 | `PP-OCRv6_small_det` | `models/PP-OCRv6_small_det_infer` | `DETECTION_MODEL_DIR` |
| 文本识别 | `PP-OCRv6_medium_rec` | `models/PP-OCRv6_medium_rec` | `RECOGNITION_MODEL_DIR` |
| 文档方向分类（0/90/180/270） | `PP-LCNet_x1_0_doc_ori` | `models/PP-LCNet_x1_0_doc_ori` | `DOC_ORIENTATION_MODEL_DIR` |

每个目录都必须包含 `inference.yml`，代码从中读取 `Global.model_name`。

检测模型也有精度更高、速度更慢的 `PP-OCRv6_medium_det` 可选，换用时把 `DETECTION_MODEL_DIR` 指向它即可。

## Git 下载

请确保 lfs 已经被正确安装（Ubuntu: `sudo apt-get install -y git-lfs`）。

```bash
cd models
git lfs install

git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_small_det.git
mv PP-OCRv6_small_det PP-OCRv6_small_det_infer   # 目录名需匹配 DETECTION_MODEL_DIR 默认值

git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_medium_rec.git
git clone https://www.modelscope.cn/PaddlePaddle/PP-LCNet_x1_0_doc_ori.git
```

不想改目录名的话，也可以保留 `PP-OCRv6_small_det`，并在 `.env` 里设置
`DETECTION_MODEL_DIR=models/PP-OCRv6_small_det`。

如果您希望跳过 lfs 大文件下载，可以使用如下命令：

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_medium_rec.git
```

> 注意：跳过 lfs 只适合查看仓库结构，缺少权重文件的模型目录无法用于推理。

## 校验

```bash
ls models/PP-OCRv6_small_det_infer/inference.yml \
   models/PP-OCRv6_medium_rec/inference.yml \
   models/PP-LCNet_x1_0_doc_ori/inference.yml
```

三个文件都存在才算下载完整。若权重文件大小只有一两百字节，说明 lfs 没有正确拉取，在对应目录执行 `git lfs pull` 补齐。

## 转换为 ONNX（可选，用于 `INFERENCE_ENGINE=onnxruntime`）

paddlepaddle 3.3.1 的 oneDNN 与 PP-OCRv6 不兼容（见 `app/config.py` 的 `ENABLE_MKLDNN`），
paddle 后端只能走未加速的通用 CPU 算子。改用 ONNX Runtime 可绕开该后端。

模型目录约定：只要目录里同时有 `inference.yml` 和 **`inference.onnx`**，服务就能用；
转换可以直接输出到原目录，无需改动 `*_MODEL_DIR` 配置。

`./models` 在 compose 里是只读挂载，用一次性容器以读写方式挂载来转换：

```bash
cd <项目根目录>
docker run --rm -v "$PWD/models:/models" unicom-ocr-detect:latest sh -c '
  uv pip install paddle2onnx
  for m in PP-OCRv6_small_det_infer PP-OCRv6_medium_rec PP-LCNet_x1_0_doc_ori; do
    paddlex --paddle2onnx --paddle_model_dir /models/$m \
            --onnx_model_dir /models/$m --opset_version 14
  done
'

ls -l models/*/inference.onnx
```

`--opset_version` 默认是 `7`，太低会用不上 ONNX Runtime 的多数图优化，务必显式指定 14 或更高。

转换完成后在 `.env` 中启用：

```bash
INFERENCE_ENGINE=onnxruntime
```

`inference.onnx` 与原 paddle 权重可以共存，切回 `INFERENCE_ENGINE=paddle` 无需删除文件。

## 确认仓库名是否有效

modelscope 仓库名如有变化，可用如下方式探测（`200` 表示存在）：

```bash
for n in PP-OCRv6_small_det PP-OCRv6_medium_det PP-OCRv6_medium_rec PP-LCNet_x1_0_doc_ori; do
  printf "%-30s %s\n" "$n" \
    "$(curl -s -o /dev/null -w '%{http_code}' https://www.modelscope.cn/api/v1/models/PaddlePaddle/$n)"
done
```

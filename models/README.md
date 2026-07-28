# 模型下载 - modelscope

服务启动后按需加载三个模型目录，缺一不可（方向分类模型只在 0° 结果未通过质量门时才加载，但生产环境必须提前准备好）：

| 目录 | 用途 | 对应配置项 |
|---|---|---|
| `models/PP-OCRv6_small_det_infer` | 文本检测 | `DETECTION_MODEL_DIR` |
| `models/PP-OCRv6_medium_rec` | 文本识别 | `RECOGNITION_MODEL_DIR` |
| `models/PP-LCNet_x1_0_doc_ori` | 文档方向分类（0/90/180/270） | `DOC_ORIENTATION_MODEL_DIR` |

每个目录都必须包含 `inference.yml`，代码从中读取 `Global.model_name`。

## Git 下载

请确保 lfs 已经被正确安装（Ubuntu: `sudo apt-get install -y git-lfs`）。

```bash
cd models
git lfs install

git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_small_det_infer.git
git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_medium_rec.git
git clone https://www.modelscope.cn/PaddlePaddle/PP-LCNet_x1_0_doc_ori.git
```

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

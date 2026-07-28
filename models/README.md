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

## 确认仓库名是否有效

modelscope 仓库名如有变化，可用如下方式探测（`200` 表示存在）：

```bash
for n in PP-OCRv6_small_det PP-OCRv6_medium_det PP-OCRv6_medium_rec PP-LCNet_x1_0_doc_ori; do
  printf "%-30s %s\n" "$n" \
    "$(curl -s -o /dev/null -w '%{http_code}' https://www.modelscope.cn/api/v1/models/PaddlePaddle/$n)"
done
```

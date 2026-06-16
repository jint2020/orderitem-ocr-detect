# 模型下载 - modelscope
Git下载

请确保 lfs 已经被正确安装

```bash
cd models
git lfs install
# PP-OCRv6_small_det_infer
# PP-OCRv6_medium_det_infer
# PP-OCRv6_medium_rec
git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_medium_rec.git

```
如果您希望跳过 lfs 大文件下载，可以使用如下命令

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://www.modelscope.cn/PaddlePaddle/PP-OCRv6_medium_rec.git
```
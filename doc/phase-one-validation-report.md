# 第一阶段 OCR 快速验证报告

## 验证目标

使用当前项目内已下载模型和快速验证数据集，验证移动端 App 订单页截图/照片的四个字段抽取能力：

- `号码`
- `日期`
- `姓名`
- `套餐信息`

本次验证不使用多模态大语言模型，采用 PaddleOCR 检测 + 识别 + 规则抽取方案。

## 验证环境

- Python 管理工具：`uv`
- Python：`3.12.12`
- OCR 框架：`paddleocr==3.7.0`
- 推理后端：CPU
- 检测模型：`models/PP-OCRv6_small_det_infer`
- 识别模型：`models/PP-OCRv6_medium_rec`
- 验证数据：`data/validation`
- 输出目录：`outputs/validation`
- 标注图目录：`outputs/validation/label_img`
- 方向处理：EXIF 方向归一化；字段质量不合格时自动尝试 `0/90/180/270` 度候选

## 运行命令

```bash
uv sync
uv run pytest -q
uv run ocr-validate
```

如需保存运行日志：

```bash
uv run ocr-validate 2>&1 | tee outputs/validation/run.log
```

## 自动化测试结果

```text
14 passed in 0.04s
```

测试覆盖：

- 验证图片发现。
- PaddleOCR 结果格式归一化。
- `label-value` 同行抽取。
- 文件名号码兜底。
- `客户名称` 到 `姓名` 的别名匹配。
- 单 OCR 文本中 `label：value` 的拆分。
- 订单时间优先于筛选日期区间。
- 手机号去除 `复制` 等 UI 操作词。
- 紧凑时间格式规整。
- 本地模型 `inference.yml` 中 `model_name` 自动读取。
- 字段质量校验会拒绝明显错误但 OCR 高置信的字段值。
- 原图字段质量不合格时，会尝试旋转候选并选择字段质量最高的结果。

## 验证结果摘要

```json
{
  "image_count": 5,
  "elapsed_seconds": 26.9359,
  "avg_seconds_per_image": 5.3872,
  "field_populated_count": {
    "号码": 5,
    "日期": 5,
    "姓名": 5,
    "套餐信息": 5
  },
  "field_need_confirm_count": {
    "号码": 0,
    "日期": 5,
    "姓名": 0,
    "套餐信息": 0
  }
}
```

## 日志输出说明

验证脚本会向 stdout 输出带 `[ocr-validate]` 前缀的进度日志，便于定位慢图片、模型路径、单图 OCR 数量和字段抽取情况。

日志包含：

- 验证开始时间点的输入目录、输出目录和图片数量。
- 检测模型与识别模型目录。
- 每张图片的开始和结束。
- 每个方向候选的字段质量分和有效字段。
- 每张图片最终选择的方向。
- 每张图片耗时、OCR 文本数量、字段填充数量、需要确认字段数量。
- 每张图片 JSON 报告写入路径。
- 每张图片标注图写入路径。
- 汇总统计和 `summary.json` 写入路径。

示例：

```text
[ocr-validate] start images=5 input_dir=data/validation output_dir=outputs/validation
[ocr-validate] model det_dir=models/PP-OCRv6_small_det_infer rec_dir=models/PP-OCRv6_medium_rec device=cpu
[ocr-validate] image start 1/5 13242337390.jpg
[ocr-validate] orientation candidate rotation=0 score=12.9375 acceptable=True valid={'号码': True, '日期': True, '姓名': True, '套餐信息': True}
[ocr-validate] orientation selected rotation=0 score=12.9375 acceptable=True
[ocr-validate] image done 1/5 13242337390.jpg elapsed=5.52s ocr_items=49 populated=4/4 need_confirm=1/4
[ocr-validate] report written outputs/validation/13242337390.json
[ocr-validate] label image written outputs/validation/label_img/13242337390.jpg
[ocr-validate] summary images=5 elapsed=26.78s avg=5.36s populated={'号码': 5, '日期': 5, '姓名': 5, '套餐信息': 5} need_confirm={'号码': 0, '日期': 5, '姓名': 0, '套餐信息': 0}
[ocr-validate] summary written outputs/validation/summary.json
```

## 输出文件说明

每张图片会生成一个 JSON 文件：

```text
outputs/validation/<图片名>.json
```

单图报告包含：

- `image`：原始图片路径。
- `elapsed_seconds`：单图推理和抽取耗时。
- `selected_rotation_degrees`：最终采用的图片方向。
- `field_quality`：最终候选的字段质量评分和字段有效性。
- `orientation_candidates`：各方向候选的压缩对比信息。
- `label_image`：框选后的标注图路径。
- `fields`：四个字段的值、置信度、来源、候选值和是否需要确认。
- `raw_ocr`：归一化后的 OCR 文本、置信度和文本框。

标注图输出目录：

```text
outputs/validation/label_img
```

标注图中蓝色框表示所有 OCR 文本区域，红色框表示已抽取字段 value 区域。如果最终选择了旋转候选，标注图会保存为旋转后的方向，确保框和文字内容对齐。

汇总文件：

```text
outputs/validation/summary.json
```

汇总报告包含图片数量、总耗时、平均耗时、各字段填充数量、各字段需确认数量和单图报告列表。

## 字段抽取明细

| 图片 | 号码 | 日期 | 姓名 | 套餐信息 |
| --- | --- | --- | --- | --- |
| `13242337390.jpg` | `13242337390` | `2026.06.10 17:51:38` | `廖**` | `全月-广东流量王黄金尊享400-预存200` |
| `16620328046.jpg` | `16620328046` | `2026.06.11 14:44:30` | `黄**` | `广东流量王白银畅享220` |
| `16676765838.jpg` | `16676765838` | `2026.06.11 17:47:27` | `单**` | `广东流量王白银畅享220` |
| `17576086667.jpg` | `17576086667` | `2026.06.12 10:28:35` | `伍**` | `联通智家5G全家福智家版79元(广东)` |
| `18565393025.jpg` | `18565393025` | `2026.06.11 15:46:45` | `何**` | `全月-广东流量王白银畅享220-预存200` |

## 观察结论

1. 本地 `PP-OCRv6_small_det_infer` + `PP-OCRv6_medium_rec` 可以跑通完整 OCR 流程。
2. 五张验证图均成功抽取四个目标字段，说明第一阶段方案可继续推进。
3. `号码`、`姓名`、`套餐信息` 主要通过明确 label-value 关系抽取，置信度较高。
4. `日期` 当前通过订单时间样式匹配抽取，已规避顶部筛选日期区间，但仍建议前端标记为需确认。
5. 单个 OCR 文本中包含 `套餐名称：xxx` 的情况很常见，抽取逻辑必须支持 inline label-value。
6. 业务页面中存在 `复制` 等 UI 操作词，需要字段级清洗。
7. 横置照片会破坏当前行聚类假设，必须先通过字段质量判断识别失败，再触发多角度候选选择。
8. `424c523431a155a4e2596945560be68b.jpg` 这类横置样例中，0 度候选会被质量校验拒绝，90 度候选可恢复为 `18665011878`、`王**`、`广东流量王白银畅享220`。

## 当前限制

- 本次样本量只有 5 张，只能证明链路可跑通，不能证明泛化准确率。
- 当前没有人工标注真值文件，字段正确性是基于 OCR 输出和人工检查总结。
- `日期` 字段的业务定义仍需确认：是订单创建时间、完成时间、办理时间，还是筛选区间中的日期。
- 姓名样本均为脱敏形式，如 `廖**`，系统当前保留脱敏值。
- 当前运行在 CPU 上，平均每张约 5.39 秒，后续需要结合服务器并发目标做性能评估。
- 多角度候选只在 0 度质量不合格时触发；触发后单图耗时会接近多次 OCR 叠加。
- 当前没有下载 PaddleOCR 方向分类或文档矫正模型，因此方向优化采用业务层候选选择，而不是模型内置方向分类。

## 下一步建议

1. 增加 `data/validation/labels.json`，为每张图片标注四个字段真值。
2. 将验证脚本升级为可计算字段准确率，而不仅是字段填充率。
3. 明确 `日期` 的业务 label，优先用 label-value 关系抽取，减少纯 pattern 兜底。
4. 扩充样本到 100-300 张，覆盖截图、拍照、模糊、反光、深色模式和不同页面模板。
5. 按错误类型决定优化方向：规则优化优先，只有 OCR 检测/识别稳定出错时再考虑微调模型。
6. 收集更多横置、倒置、轻微倾斜、反光和拍摄透视样本，评估多角度候选的触发率和耗时。

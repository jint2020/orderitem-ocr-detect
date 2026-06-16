# 当前阶段 OCR 识别过程技术文档

## 1. 文档目的

本文说明当前阶段已经实现并验证通过的 OCR 识别流程。它面向后续接手开发、调试、评估和产品联调的同学，重点解释系统如何从一张移动端 App 订单页截图/照片中识别并抽取以下四个字段：

- `号码`
- `日期`
- `姓名`
- `套餐信息`

当前阶段是第一阶段快速验证，不是最终生产版服务。目标是验证链路可行性，并沉淀可复用的 OCR 推理、字段抽取、日志和报告结构。

## 2. 当前阶段范围

当前链路处理的输入是 `data/validation` 下的订单页图片，格式支持：

- `.jpg`
- `.jpeg`
- `.png`
- `.webp`

当前默认模型为：

- 文本检测模型：`models/PP-OCRv6_small_det_infer`
- 文本识别模型：`models/PP-OCRv6_medium_rec`

当前默认输出目录为：

```text
outputs/validation
```

框选后的可视化图片输出目录为：

```text
outputs/validation/label_img
```

当前阶段不做：

- 多模态大语言模型识别。
- OCR 模型训练或微调。
- 前端交互。
- 服务化 API 封装。
- 字段准确率计算，因为当前还没有人工标注真值文件。

## 3. 运行入口

命令入口定义在 `pyproject.toml`：

```toml
[project.scripts]
ocr-validate = "unicom_ocr_detect.run_validation:main"
```

常用运行命令：

```bash
uv sync
uv run pytest -q
uv run ocr-validate
```

保存日志：

```bash
uv run ocr-validate 2>&1 | tee outputs/validation/run.log
```

指定参数运行：

```bash
uv run ocr-validate \
  --images data/validation \
  --det-model-dir models/PP-OCRv6_small_det_infer \
  --rec-model-dir models/PP-OCRv6_medium_rec \
  --output-dir outputs/validation
```

快速 smoke test：

```bash
uv run ocr-validate --limit 1
```

## 4. 模块职责

当前代码结构如下：

```text
src/unicom_ocr_detect/
  __init__.py
  images.py
  ocr_result.py
  fields.py
  field_quality.py
  visualization.py
  run_validation.py
```

### 4.1 `run_validation.py`

负责完整验证流程：

1. 解析 CLI 参数。
2. 发现输入图片。
3. 校验模型目录。
4. 构建 PaddleOCR pipeline。
5. 对每张图片执行方向候选 OCR。
6. 归一化 PaddleOCR 输出。
7. 抽取四个目标字段。
8. 评估字段质量并选择最佳方向。
9. 写入单图 JSON 报告。
10. 写入 `label_img` 框选可视化图片。
11. 写入 `summary.json` 汇总报告。
12. 输出 `[ocr-validate]` 前缀运行日志。

### 4.2 `images.py`

负责图片发现和方向候选图片生成：

- 检查输入路径是否存在。
- 检查输入路径是否为目录。
- 只保留支持的图片后缀。
- 按文件名排序，保证每次验证顺序稳定。
- 对手机照片先执行 EXIF 方向归一化。
- 当原图字段质量不达标时，生成 `90/180/270` 度候选图用于 OCR fallback。

### 4.3 `ocr_result.py`

负责把 PaddleOCR 3.x 的结果转换为统一结构 `OcrItem`。

统一后的结构包含：

```python
OcrItem(
    text="号码：",
    score=0.99,
    box=(x1, y1, x2, y2),
)
```

其中：

- `text`：识别文本。
- `score`：OCR 置信度。
- `box`：文本框外接矩形。

### 4.4 `fields.py`

负责从 OCR 文本中抽取业务字段。

输出结构为 `FieldResult`：

```python
FieldResult(
    value="13800001234",
    confidence=0.99,
    box=(x1, y1, x2, y2),
    source="label_value",
    candidates=("13800001234",),
)
```

字段会被序列化为 JSON，供前端或评估脚本使用。

### 4.5 `field_quality.py`

负责对字段结果做业务级质量评估：

- `号码` 必须是 11 位大陆手机号。
- `日期` 必须包含日期样式。
- `姓名` 不能混入日期、手机号、订单编号、搜索栏等噪声。
- `套餐信息` 不能混入日期、时间、搜索栏等噪声，且需要有一定文本长度。

字段质量分用于选择图片方向，也用于把明显不可信字段的置信度降到确认阈值以下。

### 4.6 `visualization.py`

负责输出框选后的可视化图片：

- 蓝色框：所有 OCR 检测/识别出的文本区域。
- 红色框：已抽取字段的 value 区域。
- 红色标签：字段名，例如 `号码`、`姓名`。

标注图用于人工快速检查，不作为机器消费的权威结果。机器消费仍以 JSON 中的 `fields` 和 `raw_ocr` 为准。

## 5. 识别流程总览

当前阶段完整流程如下：

```text
读取输入图片
  -> 加载本地检测模型和识别模型
  -> 生成方向候选，先尝试 0 度
  -> PaddleOCR 检测文字框并识别文字内容
  -> 归一化 OCR 结果为 OcrItem
  -> 按坐标重建行结构
  -> 按字段优先级抽取 value
  -> 字段值清洗和格式规整
  -> 字段质量评分
  -> 若 0 度质量不合格，则尝试 90/180/270 度
  -> 选择字段质量分最高的方向候选
  -> 生成单图报告
  -> 生成框选可视化图片
  -> 生成汇总报告
  -> 输出运行日志
```

## 6. 模型加载过程

模型加载发生在 `run_validation.py` 的 `_build_paddleocr()`。

当前使用 PaddleOCR 3.x pipeline：

```python
PaddleOCR(
    text_detection_model_name=read_model_name(det_model_dir),
    text_detection_model_dir=str(det_model_dir),
    text_recognition_model_name=read_model_name(rec_model_dir),
    text_recognition_model_dir=str(rec_model_dir),
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    device="cpu",
)
```

注意点：

1. 当前显式使用 CPU。
2. 当前关闭文档方向分类。
3. 当前关闭文档矫正。
4. 当前关闭文本行方向分类。
5. 当前从本地 `inference.yml` 读取 `Global.model_name`。

读取模型名是必要的。PaddleOCR 会校验传入的 `text_detection_model_name` 是否与模型目录中的配置一致。如果只传模型目录，不传正确模型名，可能出现类似“expected medium but config has small”的模型名不匹配错误。

## 7. 图片发现过程

图片发现发生在 `discover_images()`：

```python
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
```

处理逻辑：

1. 输入目录不存在时抛出 `FileNotFoundError`。
2. 输入路径不是目录时抛出 `NotADirectoryError`。
3. 忽略非图片文件。
4. 返回排序后的图片路径列表。

排序的目的是让每次验证结果稳定，方便对比日志和 JSON 报告。

## 8. 图片方向候选过程

手机拍摄图片可能横置、倒置，或者带有 EXIF 方向信息。当前没有使用 PaddleOCR 的文档方向分类模型，因此在业务层做轻量方向治理。

候选角度固定为：

```python
(0, 90, 180, 270)
```

处理策略：

1. 先用 Pillow `ImageOps.exif_transpose()` 应用 EXIF 方向。
2. 对 0 度候选执行 OCR 和字段抽取。
3. 如果 0 度字段质量可接受，则直接返回，避免额外 CPU 开销。
4. 如果 0 度字段质量不合格，则继续尝试 90、180、270 度。
5. 每个候选都计算字段质量分。
6. 选择质量分最高的候选作为最终结果；同分时优先选择旋转代价更小的候选。

这个策略针对横置订单页照片非常有效。例如 `424c523431a155a4e2596945560be68b.jpg` 原图横置时，0 度会把顶部筛选区文字错配给 `号码/姓名/套餐信息`；自动候选后会选择 90 度，字段恢复为：

```json
{
  "号码": "18665011878",
  "日期": "2026.06.14 17:18:12",
  "姓名": "王**",
  "套餐信息": "广东流量王白银畅享220"
}
```

## 9. PaddleOCR 输出归一化

PaddleOCR 3.x 的结果对象可能是 dict，也可能是带属性的对象。当前使用 `normalize_paddle_result()` 做统一处理。

当前优先读取：

- 文本：`rec_texts` 或 `dt_texts`
- 置信度：`rec_scores` 或 `dt_scores`
- 文本框：`rec_polys`、`dt_polys` 或 `polys`

每条文本会转换成：

```json
{
  "text": "套餐名称：",
  "score": 0.98,
  "box": [337.0, 568.0, 520.0, 622.0]
}
```

文本框处理：

- 如果输入是四点 polygon，则转换为外接矩形。
- 如果输入已经是 `[x1, y1, x2, y2]`，则直接使用。
- 如果没有框，则使用 `(0.0, 0.0, 0.0, 0.0)`。

## 10. 字段抽取总策略

字段抽取入口是：

```python
extract_fields(items, image_path=image_path)
```

对每个字段按以下优先级抽取：

```text
inline label-value
  -> row label-value
  -> pattern fallback
  -> filename fallback，仅号码
  -> missing
```

四个目标字段固定为：

```python
TARGET_FIELDS = ("号码", "日期", "姓名", "套餐信息")
```

## 11. 字段别名

当前字段别名配置如下：

```python
FIELD_ALIASES = {
    "号码": ("号码", "手机号", "手机号码", "用户号码", "联系电话", "业务号码", "入网号码", "联系电话号码"),
    "日期": ("日期", "办理日期", "办理时间", "订单日期", "订单时间", "生效日期", "生效时间", "下单时间", "时间"),
    "姓名": ("姓名", "客户姓名", "客户名称", "用户姓名", "用户名称", "联系人", "机主姓名"),
    "套餐信息": ("套餐信息", "套餐", "资费套餐", "产品名称", "套餐名称"),
}
```

别名匹配前会移除：

- 空白字符
- 中文冒号 `：`
- 英文冒号 `:`
- 竖线
- 中划线
- 下划线

当前 label 匹配采用“归一化后精确匹配”。这样可以避免把 `5G畅享套餐129元` 误判为 `套餐` label。

## 12. Inline Label-Value 抽取

有些 OCR 结果会把 label 和 value 识别成同一个文本块，例如：

```text
套餐名称：全月-广东流量王白银畅享220-预存200
```

这种情况由 `_extract_inline_label_value()` 处理。

处理逻辑：

1. 判断文本是否以某个字段别名开头。
2. 尝试用 `:` 或 `：` 拆分。
3. 如果拆出 value，则作为字段结果返回。

输出来源：

```text
source = "inline_label_value"
```

该策略当前主要解决 `套餐信息` 的抽取问题。

## 13. Row Label-Value 抽取

如果没有 inline value，则进入按行抽取。

### 13.1 行结构重建

`_group_rows()` 会按 OCR 文本框坐标重建行：

1. 按 `center_y` 排序。
2. 判断当前文本框是否和已有行在同一 y 范围内。
3. 同一行内按 x 坐标排序。

同一行判断阈值：

```python
abs(item.center_y - avg_y) <= max(12.0, avg_height * 0.65)
```

### 13.2 同行 value 查找

如果某个 item 被识别为 label：

1. 优先取同一行右侧文本作为候选 value。
2. 如果同一行没有候选，则取下一行文本。
3. 过滤掉其他 label。
4. 将候选 value 文本拼接。
5. 合并候选 value 的文本框。

输出来源：

```text
source = "label_value"
```

当前 `号码`、`姓名` 和部分 `套餐信息` 主要通过这个路径抽取。

## 14. Pattern Fallback 抽取

如果没有 label-value 结果，则进入 pattern fallback。

### 14.1 号码 pattern

当前手机号规则：

```python
PHONE_RE = r"(?<!\d)1[3-9]\d{9}(?!\d)"
```

可识别 11 位中国大陆手机号。

输出来源：

```text
source = "pattern"
```

### 14.2 日期 pattern

当前日期优先匹配订单时间样式：

```python
TIMESTAMP_RE = r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s*\d{1,2}:\d{2}:\d{2}"
```

例如：

```text
2026.06.11 17:47:27
2026.06.1115:46:45
```

紧凑时间会被规整为：

```text
2026.06.11 15:46:45
```

如果没有时间戳，再匹配普通日期：

```python
DATE_RE = r"\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}日?"
```

当前日期通过 pattern 抽取时置信度为 `0.85` 或 `0.75`，因此会被标记为需要前端确认。

## 15. Filename Fallback

如果 `号码` 没有从 OCR 文本中抽出，并且图片文件名中包含手机号，则使用文件名兜底。

例如：

```text
13242337390.jpg -> 13242337390
```

输出来源：

```text
source = "filename"
```

该兜底只用于第一阶段验证，不建议作为生产主路径。

## 16. 字段值清洗

当前字段值清洗发生在 `_normalize_field_value()`。

### 16.1 号码清洗

如果 value 中包含 UI 操作词，例如：

```text
13800001234复制
```

会提取其中的 11 位手机号：

```text
13800001234
```

### 16.2 日期清洗

如果时间戳中日期和时间粘连：

```text
2026.06.1115:46:45
```

会规整为：

```text
2026.06.11 15:46:45
```

### 16.3 姓名和套餐信息

当前只做首尾空白清理。

姓名样本中存在脱敏值，例如：

```text
廖**
黄**
```

当前系统保留脱敏值，不尝试还原。

## 17. 字段质量评分与确认策略

字段结构：

```python
FieldResult(
    value=...,
    confidence=...,
    box=...,
    source=...,
    candidates=...,
)
```

是否需要确认：

```python
need_confirm = confidence < 0.9
```

当前置信度来源：

- `inline_label_value`：使用该 OCR item 的 score。
- `label_value`：取 label score 和 value 平均 score 的较小值。
- `timestamp_pattern`：固定为 `0.85`。
- `pattern`：固定为 `0.75`。
- `filename`：固定为 `0.5`。
- `missing`：固定为 `0.0`。

字段质量评分会在置信度之后做业务校验。明显不符合字段语义的结果会保留原始 value，但置信度会被压低到 `0.49`，并把 `source` 追加为 `:quality_rejected`。例如横置照片中曾出现的错误值：

```text
2026.06.14 17:18:12186650118782026.06.07-2026.06.14Q请输入订单编号17:21
```

它不可能是合法手机号，也明显混入搜索栏和筛选区文本，因此会被质量校验拒绝，触发其他角度候选。

这意味着当前日期通常会进入前端确认，因为日期业务定义尚未完全确定。

## 18. 单图 JSON 报告

每张图片会生成：

```text
outputs/validation/<image-name>.json
```

结构示例：

```json
{
  "image": "data/validation/13242337390.jpg",
  "elapsed_seconds": 5.8471,
  "selected_rotation_degrees": 0,
  "field_quality": {
    "score": 12.9375,
    "acceptable": true,
    "valid_fields": {
      "号码": true,
      "日期": true,
      "姓名": true,
      "套餐信息": true
    }
  },
  "orientation_candidates": [
    {
      "rotation_degrees": 0,
      "field_quality": {
        "acceptable": true
      }
    }
  ],
  "label_image": "outputs/validation/label_img/13242337390.jpg",
  "fields": {
    "号码": {
      "value": "13242337390",
      "confidence": 0.9996,
      "box": [628.0, 850.0, 1003.0, 894.0],
      "source": "label_value",
      "candidates": ["13242337390"],
      "need_confirm": false
    }
  },
  "raw_ocr": [
    {
      "text": "号码：",
      "score": 0.99,
      "box": [40.0, 850.0, 120.0, 894.0]
    }
  ]
}
```

说明：

- `fields` 是业务可直接消费的结构。
- `selected_rotation_degrees` 表示最终采用的输入方向。
- `field_quality` 表示最终候选的字段质量评分。
- `orientation_candidates` 保留各角度候选的压缩对比信息，便于排查。
- `raw_ocr` 保留原始 OCR 文本和框，便于排查。
- `box` 可用于前端高亮原图区域。
- `label_image` 指向框选后的人工检查图片。

## 19. 标注图输出

每张图片会额外生成一张框选图：

```text
outputs/validation/label_img/<image-name>
```

标注规则：

- 蓝色框：所有 OCR 文本区域。
- 红色框：四个目标字段中已抽取到的 value 区域。
- 红色标签：字段名。

标注图用于人工快速检查 OCR 框和字段 value 框是否落在正确位置。它不是机器消费的权威结果；接口或评估脚本仍应读取单图 JSON。

如果最终选择了旋转候选，标注图会保存为旋转后的方向，确保红框、蓝框和文字内容对齐。

## 20. 汇总 JSON 报告

汇总文件：

```text
outputs/validation/summary.json
```

当前字段：

```json
{
  "image_count": 5,
  "elapsed_seconds": 27.1375,
  "avg_seconds_per_image": 5.4275,
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
  },
  "outputs": [
    "13242337390.json",
    "16620328046.json"
  ]
}
```

注意：当前 `field_populated_count` 只表示字段被填充，不等于字段准确率。后续接入人工标注真值后，才可以计算准确率。

## 21. 日志输出

运行时日志使用 `[ocr-validate]` 前缀。

示例：

```text
[ocr-validate] start images=5 input_dir=data/validation output_dir=outputs/validation
[ocr-validate] model det_dir=models/PP-OCRv6_small_det_infer rec_dir=models/PP-OCRv6_medium_rec device=cpu
[ocr-validate] image start 1/5 13242337390.jpg
[ocr-validate] orientation candidate rotation=0 score=12.9375 acceptable=True valid={'号码': True, '日期': True, '姓名': True, '套餐信息': True}
[ocr-validate] orientation selected rotation=0 score=12.9375 acceptable=True
[ocr-validate] image done 1/5 13242337390.jpg elapsed=5.8471s ocr_items=47 populated=4/4 need_confirm=1/4
[ocr-validate] report written outputs/validation/13242337390.json
[ocr-validate] label image written outputs/validation/label_img/13242337390.jpg
[ocr-validate] summary images=5 elapsed=27.1375s avg=5.4275s populated={'号码': 5, '日期': 5, '姓名': 5, '套餐信息': 5} need_confirm={'号码': 0, '日期': 5, '姓名': 0, '套餐信息': 0}
[ocr-validate] summary written outputs/validation/summary.json
```

日志用途：

- 判断模型目录是否正确。
- 判断是否成功发现图片。
- 判断是否触发了旋转候选，以及最终选中的角度。
- 定位耗时最长的图片。
- 对比每张图 OCR item 数。
- 观察每张图字段是否全部填充。
- 观察哪些字段需要用户确认。
- 找到单图 JSON 报告位置。
- 找到框选后的标注图位置。

## 22. 当前验证结果

当前验证数据共 5 张图片，最近一次验证结果：

```json
{
  "image_count": 5,
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

结论：

- 当前样本中四个字段均可抽出。
- 日期字段仍需确认，因为当前通过时间戳 pattern 抽取，不是严格 label-value 抽取。
- 当前 CPU 平均单图耗时约 5 秒级。
- 横置照片在触发 4 角度候选时耗时约为单次 OCR 的 3-4 倍；正常 0 度质量合格时不会继续跑其他角度。

## 23. 当前限制

1. **样本量小**
   当前只有 5 张验证图片，不能代表生产泛化能力。

2. **没有真值标注**
   当前只能统计字段填充率，不能自动统计字段准确率。

3. **日期定义未完全确定**
   当前优先抽取订单时间样式，业务侧仍需确认 `日期` 的精确定义。

4. **规则仍偏验证阶段**
   当前规则针对已有样本做了基础增强，后续页面模板变多后需要继续沉淀别名和布局规则。

5. **未做服务化**
   当前是 CLI 验证脚本，不是 HTTP 服务。

6. **未做并发和性能优化**
   当前 CPU 单图约 5 秒级，后续需要结合服务器规格和并发目标评估。

7. **旋转 fallback 有额外 CPU 成本**
   只有 0 度质量不合格时才会触发多角度 OCR，但极端情况下单图会跑 4 次 OCR。

## 24. 后续演进建议

### 24.1 增加标注文件

建议增加：

```text
data/validation/labels.json
```

示例：

```json
{
  "13242337390.jpg": {
    "号码": "13242337390",
    "日期": "2026.06.10 17:51:38",
    "姓名": "廖**",
    "套餐信息": "全月-广东流量王黄金尊享400-预存200"
  }
}
```

这样可以计算：

- 单字段准确率。
- 四字段全对率。
- 失败样本列表。
- 错误类型分布。

### 24.2 明确日期字段业务语义

需要确认 `日期` 是：

- 订单创建时间
- 订单完成时间
- 订单办理时间
- 生效时间
- 页面顶部筛选日期
- 其他业务时间

确认后应优先使用明确 label-value 抽取，而不是 pattern fallback。

### 24.3 增加错误归因

后续报告可以增加错误类型：

- OCR 漏检。
- OCR 识别错。
- label 未命中。
- value 配对错误。
- 字段清洗错误。
- 业务定义不明确。

### 24.4 服务化封装

当 CLI 验证稳定后，可以封装 HTTP API：

```text
POST /ocr/order-page
```

返回结构沿用当前单图 JSON 中的 `fields` 和 `raw_ocr`。

### 24.5 性能优化

后续可评估：

- 使用更小检测模型。
- 调整输入图片尺寸。
- 批量识别。
- 进程常驻加载模型。
- ONNXRuntime 部署。
- 异步队列。

### 24.6 方向模型和矫正模型

当前本地只有检测模型和识别模型，没有方向分类模型或文档矫正模型。若后续服务器资源允许，可评估补充 PaddleOCR 文档方向分类、文本行方向分类或透视矫正能力。现阶段优先使用可解释的方向候选策略。

## 25. 排查指南

### 25.1 模型名不匹配

现象：

```text
Model name mismatch
```

原因：

PaddleOCR 传入的模型名和模型目录 `inference.yml` 中的 `Global.model_name` 不一致。

当前代码已通过 `read_model_name()` 自动读取模型名。

### 25.2 图片未被发现

检查：

- `--images` 是否指向目录。
- 图片后缀是否在 `.jpg/.jpeg/.png/.webp` 中。
- 目录下是否只有子目录没有图片文件。

### 25.3 字段为空

排查步骤：

1. 打开单图 JSON。
2. 查看 `raw_ocr` 是否识别出了对应文字。
3. 如果 `raw_ocr` 没有文字，属于 OCR 检测或识别问题。
4. 如果 `raw_ocr` 有文字但 `fields` 为空，属于字段别名或布局规则问题。
5. 如果字段值包含多余 UI 文案，属于字段清洗问题。

### 25.4 日期不符合预期

当前日期是 pattern fallback，优先订单时间样式。若业务需要其他日期，需先明确字段 label，再调整 `FIELD_ALIASES` 或增加日期专用抽取规则。

### 25.5 标注图未生成

检查：

- `outputs/validation/label_img` 目录是否存在。
- 单图 JSON 中是否有 `label_image` 字段。
- 原始图片是否能被 Pillow 打开。
- 运行日志中是否出现 `label image written`。

### 25.6 横置图片抽取错误

检查单图 JSON：

- `selected_rotation_degrees` 是否为 `90/180/270`。
- `orientation_candidates` 中 0 度候选的 `field_quality.acceptable` 是否为 `false`。
- 被拒绝字段的 `source` 是否包含 `quality_rejected`。
- `label_img` 中红框是否落在正确字段 value 上。

如果四个角度均不合格，通常说明问题不只是方向，而可能是模糊、反光、页面裁切、字段别名缺失或 OCR 漏检。

## 26. 小结

当前阶段已经完成一条可运行、可测试、可观察的 OCR 快速验证链路：

```text
本地图片
  -> PaddleOCR 检测
  -> PaddleOCR 识别
  -> OCR 结果归一化
  -> label-value / pattern 字段抽取
  -> 字段清洗
  -> 字段质量评分
  -> 必要时多角度候选选择
  -> JSON 报告
  -> 框选可视化图片
  -> 日志输出
```

它证明了在当前验证图片上，使用 `PP-OCRv6_small_det_infer` 和 `PP-OCRv6_medium_rec` 可以抽取四个目标字段，并且对横置照片可通过自动方向候选恢复字段配对。下一阶段的关键工作不是直接训练模型，而是补充真值标注、扩大样本集、明确日期语义，并将验证脚本升级为可计算准确率的评估工具。

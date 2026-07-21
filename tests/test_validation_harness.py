import base64
import io
from io import BytesIO
from pathlib import Path

from PIL import Image
from werkzeug.datastructures import FileStorage

from app.models.ocr_models import OcrItem, extract_orientation_angle, normalize_paddle_result
from app.services.field_extraction import extract_fields
from app.services.field_quality import apply_quality_to_fields, evaluate_fields
from app.services.ocr_service import OcrService
from app.services.paddle_ocr_provider import read_model_name


def test_normalize_paddle_result_accepts_res_dict_with_polys_and_scores():
    raw_result = {
        "res": {
            "rec_texts": ["号码", "13800001234"],
            "rec_scores": [0.99, 0.97],
            "rec_polys": [
                [[10, 10], [60, 10], [60, 30], [10, 30]],
                [[200, 10], [360, 10], [360, 30], [200, 30]],
            ],
        }
    }

    assert normalize_paddle_result(raw_result) == [
        OcrItem(text="号码", score=0.99, box=(10.0, 10.0, 60.0, 30.0)),
        OcrItem(text="13800001234", score=0.97, box=(200.0, 10.0, 360.0, 30.0)),
    ]


def test_extract_orientation_angle_reads_angle_from_doc_preprocessor_res():
    raw = {"res": {"doc_preprocessor_res": {"angle": 90}, "rec_texts": []}}
    assert extract_orientation_angle(raw) == 90


def test_extract_orientation_angle_defaults_to_zero_when_missing():
    raw = {"res": {"rec_texts": []}}
    assert extract_orientation_angle(raw) == 0


def test_extract_fields_matches_same_row_label_value_pairs():
    items = [
        OcrItem(text="号码", score=0.99, box=(10, 10, 60, 30)),
        OcrItem(text="13800001234", score=0.97, box=(200, 10, 360, 30)),
        OcrItem(text="日期", score=0.98, box=(10, 60, 60, 80)),
        OcrItem(text="2026-06-14", score=0.96, box=(200, 60, 360, 80)),
        OcrItem(text="姓名", score=0.99, box=(10, 110, 60, 130)),
        OcrItem(text="张三", score=0.95, box=(200, 110, 260, 130)),
        OcrItem(text="套餐信息", score=0.98, box=(10, 160, 100, 180)),
        OcrItem(text="5G畅享套餐129元", score=0.94, box=(200, 160, 430, 180)),
    ]

    fields = extract_fields(items)

    assert fields["号码"].value == "13800001234"
    assert fields["日期"].value == "2026-06-14"
    assert fields["姓名"].value == "张三"
    assert fields["套餐信息"].value == "5G畅享套餐129元"


def test_extract_fields_strips_copy_suffix_from_phone_number():
    items = [
        OcrItem(text="号码：", score=0.99, box=(10, 10, 60, 30)),
        OcrItem(text="13800001234复制", score=0.97, box=(200, 10, 380, 30)),
    ]

    fields = extract_fields(items)

    assert fields["号码"].value == "13800001234"


def test_extract_fields_uses_filename_phone_as_fallback_when_enabled():
    items = [
        OcrItem(text="日期", score=0.98, box=(10, 60, 60, 80)),
        OcrItem(text="2026年06月14日", score=0.96, box=(200, 60, 400, 80)),
    ]

    fields = extract_fields(
        items,
        image_path=Path("13242337390.jpg"),
        allow_filename_fallback=True,
    )

    assert fields["号码"].value == "13242337390"
    assert fields["号码"].source == "filename"


def test_extract_fields_disables_filename_phone_fallback_by_default():
    items = [
        OcrItem(text="日期", score=0.98, box=(10, 60, 60, 80)),
        OcrItem(text="2026年06月14日", score=0.96, box=(200, 60, 400, 80)),
    ]

    fields = extract_fields(items, image_path=Path("13242337390.jpg"))

    assert fields["号码"].value == ""
    assert fields["号码"].source == "missing"


def test_extract_fields_reads_customer_name_alias():
    items = [
        OcrItem(text="客户名称：", score=0.99, box=(10, 10, 100, 30)),
        OcrItem(text="廖**", score=0.97, box=(200, 10, 260, 30)),
    ]

    fields = extract_fields(items)

    assert fields["姓名"].value == "廖**"


def test_extract_fields_picks_name_above_label_when_value_box_is_offset():
    # 真实订单页布局：value 文本框比 label 高 ~30px，行聚类把同一行的
    # label/value 拆成两行；下一行是“联系电话”的手机号。姓名应取上方
    # 的真实姓名，而不是下方的手机号。
    items = [
        OcrItem(text="18520566872复制", score=0.98, box=(552, 668, 822, 717)),
        OcrItem(text="号码：", score=0.99, box=(158, 697, 237, 739)),
        OcrItem(text="李**", score=0.96, box=(759, 722, 827, 766)),
        OcrItem(text="客户名称：", score=0.99, box=(163, 753, 298, 797)),
        OcrItem(text="13925139468复制", score=0.97, box=(557, 782, 827, 833)),
        OcrItem(text="联系电话：", score=0.99, box=(166, 811, 301, 853)),
    ]

    fields = extract_fields(items)

    assert fields["号码"].value == "18520566872"
    assert fields["姓名"].value == "李**"
    assert fields["姓名"].source == "label_value"


def test_extract_fields_splits_inline_label_value_text():
    items = [
        OcrItem(
            text="套餐名称：全月-广东流量王白银畅享220-预存200",
            score=0.98,
            box=(10, 10, 420, 30),
        )
    ]

    fields = extract_fields(items)

    assert fields["套餐信息"].value == "全月-广东流量王白银畅享220-预存200"
    assert fields["套餐信息"].source == "inline_label_value"


def test_extract_fields_prefers_order_timestamp_over_filter_date_range():
    items = [
        OcrItem(text="2026.06.04-2026.06.11", score=0.99, box=(10, 10, 250, 30)),
        OcrItem(text="16676765838", score=0.99, box=(10, 60, 180, 80)),
        OcrItem(text="已完成", score=0.99, box=(200, 60, 280, 80)),
        OcrItem(text="2026.06.11 17:47:27", score=0.98, box=(10, 100, 280, 120)),
    ]

    fields = extract_fields(items)

    assert fields["日期"].value == "2026.06.11 17:47:27"
    assert fields["日期"].source == "timestamp_pattern"


def test_extract_fields_adds_space_to_compact_timestamp():
    items = [
        OcrItem(text="2026.06.1115:46:45", score=0.98, box=(10, 10, 280, 30)),
    ]

    fields = extract_fields(items)

    assert fields["日期"].value == "2026.06.11 15:46:45"


def test_field_quality_rejects_invalid_high_confidence_field_values():
    items = [
        OcrItem(text="号码：", score=0.99, box=(10, 10, 60, 30)),
        OcrItem(text="2026.06.14 17:18:12186650118782026.06.07", score=0.99, box=(200, 10, 500, 30)),
        OcrItem(text="客户名称：", score=0.99, box=(10, 60, 100, 80)),
        OcrItem(text="2026.06.14 17:18:12Q请输入订单编号", score=0.99, box=(200, 60, 520, 80)),
        OcrItem(text="套餐名称：", score=0.99, box=(10, 110, 100, 130)),
        OcrItem(text="2026.06.14 17:18:1218665011878", score=0.99, box=(200, 110, 520, 130)),
    ]

    fields = extract_fields(items)
    quality = evaluate_fields(fields)
    calibrated = apply_quality_to_fields(fields, quality)

    assert quality.valid_fields["号码"] is False
    assert quality.valid_fields["姓名"] is False
    assert quality.valid_fields["套餐信息"] is False
    assert calibrated["号码"].need_confirm is True
    assert calibrated["姓名"].need_confirm is True
    assert calibrated["套餐信息"].need_confirm is True


def test_read_model_name_returns_global_model_name_from_inference_yml(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "inference.yml").write_text(
        "Global:\n  model_name: PP-OCRv6_small_det\n",
        encoding="utf-8",
    )

    assert read_model_name(model_dir) == "PP-OCRv6_small_det"


class AcceptableFirstCandidateFakeOcr:
    def __init__(self):
        self.calls: list[str] = []

    def predict(self, image_path: Path):
        self.calls.append(Path(image_path).name)
        return [
            {
                "res": {
                    "rec_texts": [
                        "号码：",
                        "13800001234复制",
                        "日期：",
                        "2026.06.14 17:18:12",
                        "客户名称：",
                        "张三",
                        "套餐名称：",
                        "5G畅享套餐129元",
                    ],
                    "rec_scores": [0.99, 0.98, 0.99, 0.97, 0.99, 0.96, 0.99, 0.98],
                    "rec_polys": [
                        [[10, 10], [60, 10], [60, 30], [10, 30]],
                        [[200, 10], [360, 10], [360, 30], [200, 30]],
                        [[10, 60], [60, 60], [60, 80], [10, 80]],
                        [[200, 60], [390, 60], [390, 80], [200, 80]],
                        [[10, 110], [100, 110], [100, 130], [10, 130]],
                        [[200, 110], [260, 110], [260, 130], [200, 130]],
                        [[10, 160], [100, 160], [100, 180], [10, 180]],
                        [[200, 160], [430, 160], [430, 180], [200, 180]],
                    ],
                }
            }
        ]


def _upload_file(name: str = "sample.jpg") -> FileStorage:
    stream = BytesIO()
    Image.new("RGB", (420, 160), "white").save(stream, format="JPEG")
    stream.seek(0)
    return FileStorage(stream=stream, filename=name, content_type="image/jpeg")


def test_ocr_service_returns_label_image_base64():
    service = OcrService(provider=AcceptableFirstCandidateFakeOcr())

    content = service.recognize_order_image(_upload_file(), request_id="request-1")

    assert content["request_id"] == "request-1"
    assert content["fields"]["号码"]["value"] == "13800001234"
    assert content["selected_rotation_degrees"] == 0
    assert content["label_image_base64"]
    image_bytes = base64.b64decode(content["label_image_base64"])
    with Image.open(io.BytesIO(image_bytes)) as image:
        assert image.size == (420, 160)


def test_ocr_service_reports_orientation_angle_and_runs_single_pass():
    class AngleProvider:
        def __init__(self):
            self.calls: list[Path] = []

        def predict(self, image_path: Path):
            self.calls.append(image_path)
            return [
                {
                    "res": {
                        "doc_preprocessor_res": {
                            "angle": 90,
                            "model_settings": {"use_doc_orientation_classify": True},
                        },
                        "rec_texts": ["号码：", "13800001234"],
                        "rec_scores": [0.99, 0.98],
                        "rec_polys": [
                            [[10, 10], [60, 10], [60, 30], [10, 30]],
                            [[200, 10], [360, 10], [360, 30], [200, 30]],
                        ],
                    }
                }
            ]

    provider = AngleProvider()
    service = OcrService(provider=provider)

    content = service.recognize_order_image(_upload_file(), request_id="request-2")

    assert len(provider.calls) == 1
    assert content["selected_rotation_degrees"] == 90
    assert content["fields"]["号码"]["value"] == "13800001234"


def test_ocr_service_disables_filename_phone_fallback_for_api_uploads():
    class DateOnlyProvider:
        def predict(self, image_path: Path):
            return [
                {
                    "res": {
                        "rec_texts": ["日期", "2026年06月14日"],
                        "rec_scores": [0.98, 0.96],
                        "rec_polys": [
                            [[10, 60], [60, 60], [60, 80], [10, 80]],
                            [[200, 60], [400, 60], [400, 80], [200, 80]],
                        ],
                    }
                }
            ]

    service = OcrService(provider=DateOnlyProvider())

    content = service.recognize_order_image(_upload_file("13242337390.jpg"), request_id="request-4")

    assert content["fields"]["号码"]["value"] == ""
    assert content["fields"]["号码"]["source"].startswith("missing")

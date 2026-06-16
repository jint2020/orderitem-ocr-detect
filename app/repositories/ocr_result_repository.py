from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage

from app.services.image_service import secure_upload_filename


@dataclass(frozen=True)
class OcrRequestWorkspace:
    request_id: str
    root_dir: Path
    original_dir: Path
    label_image_dir: Path
    report_path: Path
    original_path: Path
    label_image_path: Path
    original_key: str
    label_image_key: str
    report_key: str


class OcrResultRepository:
    def __init__(self, output_root: Path):
        self.output_root = output_root

    def create_workspace(self, request_id: str, filename: str) -> OcrRequestWorkspace:
        safe_name = secure_upload_filename(filename)
        root_dir = self.output_root / request_id
        original_dir = root_dir / "original"
        label_image_dir = root_dir / "label_img"
        original_dir.mkdir(parents=True, exist_ok=True)
        label_image_dir.mkdir(parents=True, exist_ok=True)
        return OcrRequestWorkspace(
            request_id=request_id,
            root_dir=root_dir,
            original_dir=original_dir,
            label_image_dir=label_image_dir,
            report_path=root_dir / "report.json",
            original_path=original_dir / safe_name,
            label_image_path=label_image_dir / safe_name,
            original_key=f"requests/{request_id}/original/{safe_name}",
            label_image_key=f"requests/{request_id}/label_img/{safe_name}",
            report_key=f"requests/{request_id}/report.json",
        )

    def save_original(self, workspace: OcrRequestWorkspace, file_storage: FileStorage) -> Path:
        file_storage.stream.seek(0)
        file_storage.save(workspace.original_path)
        return workspace.original_path

    def save_report(self, workspace: OcrRequestWorkspace, report: dict[str, Any]) -> Path:
        workspace.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return workspace.report_path

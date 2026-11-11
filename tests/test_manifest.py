"""
审计留痕 — 测试套件

覆盖：输入指纹随内容变化、清单可复现、清单不含敏感字段、
CLI ``--manifest`` 落盘、报告摘要与审计日志能看到输入哈希。
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from insurance_audit import __version__
from insurance_audit.audit.manifest import build_manifest, file_fingerprint
from insurance_audit.data.generator import generate_mock_data
from insurance_audit.main import run_audit
from insurance_audit.utils.logger import AuditLogger


def _make_input(tmp_path: Path, rows: int = 5) -> Path:
    path = tmp_path / "input.xlsx"
    generate_mock_data(num_records=rows, output_file=str(path), anomaly_ratio=0.0, seed=3)
    return path


@pytest.mark.unit
def test_file_fingerprint_detects_one_byte_change(tmp_path: Path) -> None:
    """改 1 个字节，哈希必须变化"""
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"abc")
    first = file_fingerprint(path)
    path.write_bytes(b"abd")
    second = file_fingerprint(path)

    assert first["bytes"] == 3
    assert second["bytes"] == 3
    assert len(first["sha256"]) == 64
    assert first["sha256"] != second["sha256"]


@pytest.mark.unit
def test_manifest_reproducible_except_generated_at(tmp_path: Path) -> None:
    """同一输入两次运行，清单除生成时间外完全一致"""
    input_file = _make_input(tmp_path)
    first = build_manifest(input_file, rows=5, output_path=tmp_path / "r.xlsx")
    second = build_manifest(input_file, rows=5, output_path=tmp_path / "r.xlsx")
    first.pop("generated_at")
    second.pop("generated_at")

    assert first == second


@pytest.mark.unit
def test_manifest_contains_version_and_config_without_secrets(tmp_path: Path) -> None:
    """清单带版本与关键配置，且不含任何密钥类字段"""
    manifest = build_manifest(_make_input(tmp_path), rows=5)

    assert manifest["tool_version"] == __version__
    assert manifest["python_version"].startswith("3.")
    assert manifest["config"]["default_ratio"] == "0.80"
    text = json.dumps(manifest, ensure_ascii=False).lower()
    for forbidden in ("secret", "password", "token", ".env"):
        assert forbidden not in text


@pytest.mark.unit
def test_cli_writes_manifest(tmp_path: Path) -> None:
    """--manifest 落盘，含行数、SHA256 与输出路径"""
    input_file = _make_input(tmp_path)
    output = tmp_path / "report.xlsx"
    manifest_path = tmp_path / "manifest.json"

    code = run_audit(input_file, output, manifest_out=manifest_path)

    assert code == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["input"]["rows"] == 5
    assert len(manifest["input"]["sha256"]) == 64
    assert manifest["output"]["path"] == str(output)


@pytest.mark.unit
def test_report_summary_contains_fingerprint(tmp_path: Path) -> None:
    """报告摘要 sheet 能看到输入哈希、字节数、工具版本"""
    input_file = _make_input(tmp_path)
    report = tmp_path / "report.xlsx"
    run_audit(input_file, report)

    summary = pd.read_excel(report, sheet_name="审计摘要")
    values = dict(zip(summary["审计项目"], summary["数值"]))
    assert values["输入文件 SHA256"] == file_fingerprint(input_file)["sha256"]
    assert values["输入文件字节数"] == input_file.stat().st_size
    assert values["工具版本"] == __version__


@pytest.mark.unit
def test_audit_log_contains_input_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """审计日志的 AUDIT_COMPLETE 事件带输入哈希"""
    input_file = _make_input(tmp_path)
    captured: list[tuple[str, str]] = []

    def fake_log(_self: AuditLogger, action: str, detail: str, _user: str = "SYSTEM") -> None:
        captured.append((action, detail))

    monkeypatch.setattr(AuditLogger, "log", fake_log)
    run_audit(input_file, tmp_path / "report.xlsx")

    expected = file_fingerprint(input_file)["sha256"]
    assert any(action == "AUDIT_COMPLETE" and expected in detail for action, detail in captured)

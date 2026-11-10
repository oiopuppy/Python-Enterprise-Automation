"""
CLI 退出码 — 测试套件

确保「出问题就返回非 0」这条约定不被破坏：
之前环境检查失败时 main() 直接 return，跳过了 sys.exit(exit_code)，
导致进程退出码永远是 0，调度系统会把失败当成成功。
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from insurance_audit import main as main_module
from insurance_audit.data.generator import generate_mock_data


def _run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    """以给定 CLI 参数调用 main()，返回退出码"""
    monkeypatch.setattr(sys, "argv", ["insurance-audit", *args])
    with pytest.raises(SystemExit) as exc_info:
        main_module.main()
    return int(exc_info.value.code)


class TestCliExitCodes:
    """CLI 退出码约定"""

    @pytest.mark.unit
    def test_missing_input_file_returns_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """数据文件不存在必须返回 1，而不是 0"""
        code = _run_main(
            monkeypatch,
            "--input",
            str(tmp_path / "not_exists.xlsx"),
            "--output",
            str(tmp_path / "report.xlsx"),
        )
        assert code == 1

    @pytest.mark.unit
    def test_clean_audit_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """全部一致的审计返回 0"""
        input_file = tmp_path / "input.xlsx"
        generate_mock_data(num_records=5, output_file=str(input_file), anomaly_ratio=0.0, seed=1)

        code = _run_main(
            monkeypatch,
            "--input",
            str(input_file),
            "--output",
            str(tmp_path / "report.xlsx"),
        )
        assert code == 0
        assert (tmp_path / "report.xlsx").exists()

    @pytest.mark.unit
    def test_audit_with_anomalies_returns_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """存在对账异常时返回 1"""
        input_file = tmp_path / "input.xlsx"
        generate_mock_data(num_records=20, output_file=str(input_file), anomaly_ratio=1.0, seed=42)

        code = _run_main(
            monkeypatch,
            "--input",
            str(input_file),
            "--output",
            str(tmp_path / "report.xlsx"),
        )
        assert code == 1

    @pytest.mark.unit
    def test_parse_errors_return_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """有无法解析的记录时返回 1，并如实写进报告"""
        df = pd.DataFrame(
            {
                "保单号": ["CL9900100", "BAD123"],
                "客户姓名": ["张三", "李四"],
                "报案金额": [1000.0, 2000.0],
                "免赔额": [500.0, 500.0],
                "赔付比例": [0.80, 0.80],
                "实际赔付金额": [400.0, 1200.0],
            }
        )
        input_file = tmp_path / "parse_error.xlsx"
        df.to_excel(input_file, index=False)

        report_file = tmp_path / "report.xlsx"
        code = _run_main(
            monkeypatch,
            "--input",
            str(input_file),
            "--output",
            str(report_file),
        )
        assert code == 1

        anomaly_df = pd.read_excel(report_file, sheet_name="异常数据")
        assert "解析失败" in set(anomaly_df["审计状态"])

    @pytest.mark.unit
    def test_json_to_stdout_is_pure_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json 把摘要打到 stdout，日志走 stderr，可直接被管道消费"""
        input_file = tmp_path / "input.xlsx"
        generate_mock_data(num_records=5, output_file=str(input_file), anomaly_ratio=0.0, seed=1)

        code = _run_main(
            monkeypatch,
            "--input",
            str(input_file),
            "--output",
            str(tmp_path / "report.xlsx"),
            "--json",
        )
        assert code == 0

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["tool_version"]
        assert payload["input"]["rows"] == 5
        assert len(payload["input"]["sha256"]) == 64
        assert payload["summary"]["source_records"] == 5
        assert payload["summary"]["matched_records"] == 5
        assert payload["summary"]["parse_error_records"] == 0
        assert payload["summary"]["match_rate"] == 100.0
        assert isinstance(payload["summary"]["total_claim_amount"], str)
        assert payload["parse_errors"] == []
        assert payload["quality_issues"] == []
        assert payload["execution_time"].endswith("s")

    @pytest.mark.unit
    def test_json_out_writes_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json-out 把同一份摘要落盘"""
        input_file = tmp_path / "input.xlsx"
        generate_mock_data(num_records=5, output_file=str(input_file), anomaly_ratio=0.0, seed=1)
        json_file = tmp_path / "summary.json"

        code = _run_main(
            monkeypatch,
            "--input",
            str(input_file),
            "--output",
            str(tmp_path / "report.xlsx"),
            "--json-out",
            str(json_file),
        )
        assert code == 0
        assert json_file.exists()

        payload = json.loads(json_file.read_text(encoding="utf-8"))
        assert payload["summary"]["source_records"] == 5
        assert payload["input"]["rows"] == 5

    @pytest.mark.integration
    def test_detail_sum_matches_summary_and_ratio_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """明细金额可直接求和且与摘要一致；比例按百分比格式显示"""
        from openpyxl import load_workbook

        df = pd.DataFrame(
            {
                "保单号": ["CL9900100", "CL9900101", "CL9900102", "BAD123"],
                "客户姓名": ["甲", "乙", "丙", "丁"],
                "报案金额": [1000.0, 2000.0, 3000.0, 5000.0],
                "免赔额": [500.0, 500.0, 500.0, 500.0],
                "赔付比例": [0.80, 0.80, 0.80, 0.80],
                "实际赔付金额": [400.0, 1200.0, 1900.0, 3600.0],
            }
        )
        input_file = tmp_path / "input.xlsx"
        df.to_excel(input_file, index=False)
        report_file = tmp_path / "report.xlsx"

        code = _run_main(
            monkeypatch,
            "--input",
            str(input_file),
            "--output",
            str(report_file),
        )
        assert code == 1

        detail = pd.read_excel(report_file, sheet_name="对账明细")
        summary = pd.read_excel(report_file, sheet_name="审计摘要")

        # 明细差异列求和 == 摘要「总差异金额」
        total_diff = float(summary.loc[summary["审计项目"] == "总差异金额", "数值"].iloc[0])
        assert round(float(detail["差异金额"].sum()), 2) == round(total_diff, 2)

        # 解析失败行的金额保持为空，不能写 0（否则污染求和）
        parse_row = detail[detail["审计状态"] == "解析失败"].iloc[0]
        assert pd.isna(parse_row["差异金额"])

        # 赔付比例：存 0.8，显示 80.00%
        wb = load_workbook(report_file)
        ws = wb["对账明细"]
        headers = [cell.value for cell in ws[1]]
        ratio_col = headers.index("赔付比例") + 1
        assert ws.cell(row=2, column=ratio_col).number_format == "0.00%"

    @pytest.mark.unit
    def test_generate_mock_writes_to_requested_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--generate-mock 必须写到 --input 指定的位置，不能落在当前工作目录"""
        target = tmp_path / "mock.xlsx"
        code = _run_main(
            monkeypatch,
            "--generate-mock",
            "--input",
            str(target),
            "--output",
            str(tmp_path / "report.xlsx"),
        )
        assert target.exists()
        # 默认会注入约 10% 的差异，因此退出码可能是 0 或 1；这里只验证落盘位置
        assert code in (0, 1)

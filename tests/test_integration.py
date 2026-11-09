"""
集成测试 — Integration Tests

测试完整的端到端工作流：
1. 数据生成 -> 文件读写 -> 对账 -> 报告
2. 异常链路
"""

from pathlib import Path

import pytest

from insurance_audit.core.engine import AuditEngine
from insurance_audit.core.validator import validate_dataframe
from insurance_audit.data.generator import generate_mock_data
from insurance_audit.data.reader import read_excel
from insurance_audit.utils.exceptions import FileNotFoundError


class TestIntegrationGenerator:
    """模拟数据生成集成测试"""

    @pytest.mark.integration
    def test_generate_and_read(self, tmp_path: Path) -> None:
        """生成并读取模拟数据"""
        output = str(tmp_path / "test_mock.xlsx")
        df = generate_mock_data(num_records=10, output_file=output)
        assert len(df) == 10

        # 读取验证
        df_read = read_excel(output)
        assert len(df_read) == 10

    @pytest.mark.integration
    @pytest.mark.parametrize("num_records", [0, 1, 100])
    def test_various_sizes(self, num_records: int, tmp_path: Path) -> None:
        """不同规模的数据生成"""
        output = str(tmp_path / f"test_{num_records}.xlsx")
        if num_records == 0:
            df = generate_mock_data(num_records=0, output_file=output)
            assert len(df) == 0
        else:
            df = generate_mock_data(num_records=num_records, output_file=output)
            assert len(df) == num_records


class TestIntegrationReadFile:
    """文件读写集成测试"""

    @pytest.mark.integration
    def test_file_not_found(self) -> None:
        """文件不存在"""
        with pytest.raises(FileNotFoundError):
            read_excel("/nonexistent/path.xlsx")

    @pytest.mark.integration
    def test_read_and_validate(self, temp_excel_file: Path) -> None:
        """读取并校验"""
        df = read_excel(str(temp_excel_file))
        errors = validate_dataframe(df)
        assert len(errors) == 0


class TestIntegrationAuditPipeline:
    """完整审计流水线测试"""

    @pytest.mark.integration
    def test_full_pipeline(self, tmp_path: Path) -> None:
        """生成 -> 对账 -> 报告（不注入差异，验证全部一致路径）"""
        # 1. 生成数据（anomaly_ratio=0 时用同一算法生成，必然全部一致）
        input_file = str(tmp_path / "input.xlsx")
        generate_mock_data(num_records=20, output_file=input_file, anomaly_ratio=0.0)

        # 2. 执行审计
        output_file = str(tmp_path / "output.xlsx")
        engine = AuditEngine(input_file=input_file, output_file=output_file)
        summary = engine.run()

        # 3. 验证
        assert summary.source_records == 20
        assert summary.total_records == 20
        assert summary.parse_error_records == 0
        assert summary.matched_records == 20
        assert summary.match_rate == 100.0

    @pytest.mark.integration
    def test_full_pipeline_with_injected_anomalies(self, tmp_path: Path) -> None:
        """默认注入差异时，审计必须能真的发现异常，而不是永远 100% 一致"""
        input_file = str(tmp_path / "input.xlsx")
        generate_mock_data(num_records=20, output_file=input_file, anomaly_ratio=1.0, seed=42)

        output_file = str(tmp_path / "output.xlsx")
        summary = AuditEngine(input_file=input_file, output_file=output_file).run()

        assert summary.source_records == 20
        assert summary.total_records == 20
        # 0 赔付的记录没有可注入的差异，所以是「绝大多数」而非全部
        assert summary.unmatched_records >= 15
        assert summary.matched_records + summary.unmatched_records == 20
        assert summary.match_rate < 50.0

    @pytest.mark.integration
    def test_pipeline_records_parse_errors(self, tmp_path: Path) -> None:
        """无法解析的行不能静默消失：行数要可核对，报告里要有「解析失败」"""
        import pandas as pd

        df = pd.DataFrame(
            {
                "保单号": ["CL9900100", "ABC123"],  # 第二条保单号非法
                "客户姓名": ["张三", "李四"],
                "报案金额": [1000.0, 2000.0],
                "免赔额": [500.0, 500.0],
                "赔付比例": [0.80, 0.80],
                "实际赔付金额": [400.0, 1200.0],
            }
        )
        input_file = str(tmp_path / "parse_error_input.xlsx")
        df.to_excel(input_file, index=False)

        output_file = str(tmp_path / "parse_error_output.xlsx")
        summary = AuditEngine(input_file=input_file, output_file=output_file).run()

        # 行数必须可核对：读取 2 = 解析成功 1 + 解析失败 1
        assert summary.source_records == 2
        assert summary.total_records == 1
        assert summary.parse_error_records == 1
        assert summary.matched_records + summary.unmatched_records == summary.total_records
        assert summary.parse_errors[0]["policy_id"] == "ABC123"
        assert summary.parse_errors[0]["row"] == 3

        # 异常 Sheet 里要能看到解析失败的那一行
        anomaly_df = pd.read_excel(output_file, sheet_name="异常数据")
        assert "解析失败" in set(anomaly_df["审计状态"])
        assert "ABC123" in set(anomaly_df["保单号"])

        # 摘要 Sheet 里要有可核对的行数
        summary_df = pd.read_excel(output_file, sheet_name="审计摘要")
        items = dict(zip(summary_df["审计项目"], summary_df["数值"]))
        assert items["读取总行数"] == 2
        assert items["无法解析"] == 1

    @pytest.mark.integration
    def test_pipeline_with_mismatches(self, tmp_path: Path) -> None:
        """含不一致数据的审计流水线"""
        # 手动制造不一致数据

        import pandas as pd

        df = pd.DataFrame(
            {
                "保单号": ["CL9900100", "CL9900101"],
                "客户姓名": ["张三", "李四"],
                "报案金额": [1000.0, 200.0],
                "免赔额": [500.0, 500.0],
                "赔付比例": [0.80, 0.80],
                "实际赔付金额": [9999.0, 0.0],  # 第一条故意不一致
            }
        )
        input_file = str(tmp_path / "bad_input.xlsx")
        df.to_excel(input_file, index=False)

        output_file = str(tmp_path / "bad_output.xlsx")
        engine = AuditEngine(input_file=input_file, output_file=output_file)
        summary = engine.run()

        assert summary.total_records == 2
        assert summary.unmatched_records == 1
        assert summary.matched_records == 1

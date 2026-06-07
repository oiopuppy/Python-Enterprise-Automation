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
        """生成 -> 对账 -> 报告"""
        # 1. 生成数据
        input_file = str(tmp_path / "input.xlsx")
        generate_mock_data(num_records=20, output_file=input_file)

        # 2. 执行审计
        output_file = str(tmp_path / "output.xlsx")
        engine = AuditEngine(input_file=input_file, output_file=output_file)
        summary = engine.run()

        # 3. 验证
        assert summary.total_records == 20
        assert summary.matched_records == 20  # 全一致（用同一算法生成）
        assert summary.match_rate == 100.0

    @pytest.mark.integration
    def test_pipeline_with_mismatches(self, tmp_path: Path) -> None:
        """含不一致数据的审计流水线"""
        # 手动制造不一致数据
        import pandas as pd
        from decimal import Decimal
        
        df = pd.DataFrame({
            "保单号": ["CL9900100", "CL9900101"],
            "客户姓名": ["张三", "李四"],
            "报案金额": [1000.0, 200.0],
            "免赔额": [500.0, 500.0],
            "赔付比例": [0.80, 0.80],
            "实际赔付金额": [9999.0, 0.0],  # 第一条故意不一致
        })
        input_file = str(tmp_path / "bad_input.xlsx")
        df.to_excel(input_file, index=False)

        output_file = str(tmp_path / "bad_output.xlsx")
        engine = AuditEngine(input_file=input_file, output_file=output_file)
        summary = engine.run()

        assert summary.total_records == 2
        assert summary.unmatched_records == 1
        assert summary.matched_records == 1

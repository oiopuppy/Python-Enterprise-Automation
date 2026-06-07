"""
数据验证层 — 全面测试套件

测试范围：
1. 列校验
2. 逐行校验（所有约束）
3. 全量DataFrame校验
4. 异常数据场景
"""

import pandas as pd
import pytest

from insurance_audit.core.validator import (
    validate_columns,
    validate_dataframe,
    validate_row,
)
from insurance_audit.utils.exceptions import DataValidationError, InvalidColumnError


class TestValidateColumns:
    """Excel列校验测试"""

    @pytest.mark.unit
    def test_all_columns_present(self, sample_dataframe: pd.DataFrame) -> None:
        """所有必需列都存在"""
        validate_columns(sample_dataframe)  # 不应抛出异常

    @pytest.mark.unit
    def test_missing_column(self) -> None:
        """缺少必需列"""
        df = pd.DataFrame({
            "保单号": ["CL9900100"],
            "客户姓名": ["张三"],
            # 缺少其他列
        })
        with pytest.raises(InvalidColumnError):
            validate_columns(df)

    @pytest.mark.unit
    def test_empty_dataframe(self) -> None:
        """空DataFrame"""
        df = pd.DataFrame()
        with pytest.raises(InvalidColumnError):
            validate_columns(df)


class TestValidateRow:
    """单行数据校验测试"""

    @pytest.mark.unit
    def test_valid_row(self) -> None:
        """有效数据行"""
        row = (0, {
            "保单号": "CL9900100",
            "客户姓名": "张三",
            "报案金额": 1000.0,
            "免赔额": 500.0,
            "赔付比例": 0.80,
            "实际赔付金额": 400.0,
        })
        is_valid, msg = validate_row(row)
        assert is_valid
        assert msg == ""

    @pytest.mark.unit
    def test_null_claim_amount(self) -> None:
        """报案金额为空"""
        row = (0, {
            "保单号": "CL9900100",
            "客户姓名": "张三",
            "报案金额": None,
            "免赔额": 500.0,
            "赔付比例": 0.80,
            "实际赔付金额": 400.0,
        })
        is_valid, msg = validate_row(row)
        assert not is_valid
        assert "为空" in msg

    @pytest.mark.unit
    def test_invalid_ratio(self) -> None:
        """赔付比例不合法"""
        row = (0, {
            "保单号": "CL9900100",
            "客户姓名": "张三",
            "报案金额": 1000.0,
            "免赔额": 500.0,
            "赔付比例": 1.5,
            "实际赔付金额": 400.0,
        })
        is_valid, msg = validate_row(row)
        assert not is_valid
        assert "不在0~1范围内" in msg

    @pytest.mark.unit
    def test_invalid_policy_id_format(self) -> None:
        """保单号格式异常"""
        row = (0, {
            "保单号": "ABC123",
            "客户姓名": "张三",
            "报案金额": 1000.0,
            "免赔额": 500.0,
            "赔付比例": 0.80,
            "实际赔付金额": 400.0,
        })
        is_valid, msg = validate_row(row)
        assert not is_valid
        assert "应以CL开头" in msg


class TestValidateDataFrame:
    """全量DataFrame校验测试"""

    @pytest.mark.unit
    def test_valid_dataframe(self, sample_dataframe: pd.DataFrame) -> None:
        """有效DataFrame"""
        errors = validate_dataframe(sample_dataframe)
        assert len(errors) == 0

    @pytest.mark.unit
    def test_partially_invalid_dataframe(self) -> None:
        """部分数据异常"""
        df = pd.DataFrame({
            "保单号": ["CL9900100", "INVALID", "CL9900102"],
            "客户姓名": ["张三", "李四", "王五"],
            "报案金额": [1000.0, 2000.0, None],
            "免赔额": [500.0, 300.0, 800.0],
            "赔付比例": [0.80, 1.50, 0.85],
            "实际赔付金额": [400.0, 1000.0, 3570.0],
        })
        errors = validate_dataframe(df)
        assert len(errors) >= 2  # 至少2条异常

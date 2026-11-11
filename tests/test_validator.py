"""
数据验证层 — 全面测试套件

测试范围：
1. 列校验
2. 逐行校验（一行多个问题全部收集）
3. 跨行检查（重复保单号、客户名不一致）
4. 全量DataFrame校验
"""

import pandas as pd
import pytest

from insurance_audit.core.validator import (
    CODE_CROSS_FIELD,
    CODE_CUSTOMER_MISMATCH,
    CODE_DUPLICATE_POLICY,
    CODE_EMPTY,
    CODE_FORMAT,
    CODE_PRECISION,
    CODE_RANGE,
    validate_columns,
    validate_dataframe,
    validate_row,
)
from insurance_audit.utils.exceptions import InvalidColumnError


def _row(**overrides: object) -> tuple[int, dict[str, object]]:
    """构造一行完整数据，按需覆盖字段"""
    data: dict[str, object] = {
        "保单号": "CL9900100",
        "客户姓名": "张三",
        "报案金额": 1000.0,
        "免赔额": 500.0,
        "赔付比例": 0.80,
        "实际赔付金额": 400.0,
    }
    data.update(overrides)
    return 0, data


class TestValidateColumns:
    """Excel列校验测试"""

    @pytest.mark.unit
    def test_all_columns_present(self, sample_dataframe: pd.DataFrame) -> None:
        """所有必需列都存在"""
        validate_columns(sample_dataframe)  # 不应抛出异常

    @pytest.mark.unit
    def test_missing_column(self) -> None:
        """缺少必需列"""
        df = pd.DataFrame(
            {
                "保单号": ["CL9900100"],
                "客户姓名": ["张三"],
                # 缺少其他列
            }
        )
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
        """有效数据行没有问题"""
        assert validate_row(_row()) == []

    @pytest.mark.unit
    def test_null_claim_amount(self) -> None:
        """报案金额为空 → EMPTY，字段是真实列名"""
        issues = validate_row(_row(**{"报案金额": None}))
        assert len(issues) == 1
        assert issues[0].code == CODE_EMPTY
        assert issues[0].field == "报案金额"

    @pytest.mark.unit
    def test_invalid_ratio(self) -> None:
        """赔付比例不合法 → RANGE"""
        issues = validate_row(_row(**{"赔付比例": 1.5}))
        assert [issue.code for issue in issues] == [CODE_RANGE]
        assert issues[0].field == "赔付比例"
        assert "不在0~1范围内" in issues[0].message

    @pytest.mark.unit
    def test_invalid_policy_id_format(self) -> None:
        """保单号格式异常 → FORMAT，字段是 保单号 而不是「综合」"""
        issues = validate_row(_row(**{"保单号": "ABC123"}))
        assert [issue.code for issue in issues] == [CODE_FORMAT]
        assert issues[0].field == "保单号"
        assert "应以CL开头" in issues[0].message

    @pytest.mark.unit
    def test_collects_multiple_issues_in_one_row(self) -> None:
        """一行里的多个问题要全部收集：空客户名 + 三位小数金额"""
        issues = validate_row(_row(**{"客户姓名": None, "报案金额": 1000.001}))
        codes = {issue.code for issue in issues}
        fields = {issue.field for issue in issues}
        assert codes == {CODE_EMPTY, CODE_PRECISION}
        assert fields == {"客户姓名", "报案金额"}

    @pytest.mark.unit
    def test_cross_field_actual_exceeds_claim(self) -> None:
        """实际赔付超过报案金额 → CROSS_FIELD（只提示，不阻断）"""
        issues = validate_row(_row(**{"实际赔付金额": 1200.0}))
        assert [issue.code for issue in issues] == [CODE_CROSS_FIELD]
        assert issues[0].field == "实际赔付金额"


class TestDuplicatePolicies:
    """跨行一致性：重复保单号 / 客户名不一致"""

    @staticmethod
    def _df(**overrides: object) -> pd.DataFrame:
        data: dict[str, object] = {
            "保单号": ["CL9900100", "CL9900100", "CL9900100"],
            "客户姓名": ["张三", "张三", "张三"],
            "报案金额": [1000.0, 2000.0, 3000.0],
            "免赔额": [500.0, 500.0, 500.0],
            "赔付比例": [0.80, 0.80, 0.80],
            "实际赔付金额": [400.0, 1200.0, 1900.0],
        }
        data.update(overrides)
        return pd.DataFrame(data)

    @pytest.mark.unit
    def test_duplicate_group_lists_all_rows(self) -> None:
        """重复保单要列出该组所有行号与金额合计"""
        issues = validate_dataframe(self._df())
        duplicates = [issue for issue in issues if issue.code == CODE_DUPLICATE_POLICY]
        assert len(duplicates) == 1
        message = duplicates[0].message
        assert "第 2、3、4 行" in message
        assert "实际赔付合计 3500.00" in message

    @pytest.mark.unit
    def test_customer_mismatch_flagged(self) -> None:
        """同一保单号对应不同客户名 → CUSTOMER_MISMATCH"""
        df = self._df(**{"客户姓名": ["张三", "李四", "张三"]})
        issues = validate_dataframe(df)
        mismatches = [issue for issue in issues if issue.code == CODE_CUSTOMER_MISMATCH]
        assert len(mismatches) == 1
        assert mismatches[0].field == "客户姓名"
        assert "张三" in mismatches[0].message
        assert "李四" in mismatches[0].message

    @pytest.mark.unit
    def test_unique_policies_not_flagged(self, sample_dataframe: pd.DataFrame) -> None:
        """保单号都不重复时不产生重复问题"""
        issues = validate_dataframe(sample_dataframe)
        assert [issue for issue in issues if issue.code == CODE_DUPLICATE_POLICY] == []


class TestValidateDataFrame:
    """全量DataFrame校验测试"""

    @pytest.mark.unit
    def test_valid_dataframe(self, sample_dataframe: pd.DataFrame) -> None:
        """有效DataFrame"""
        errors = validate_dataframe(sample_dataframe)
        assert len(errors) == 0

    @pytest.mark.unit
    def test_partially_invalid_dataframe(self) -> None:
        """部分数据异常：一行可产生多条问题，问题总数不少于异常格数"""
        df = pd.DataFrame(
            {
                "保单号": ["CL9900100", "INVALID", "CL9900102"],
                "客户姓名": ["张三", "李四", "王五"],
                "报案金额": [1000.0, 2000.0, None],
                "免赔额": [500.0, 300.0, 800.0],
                "赔付比例": [0.80, 1.50, 0.85],
                "实际赔付金额": [400.0, 1000.0, 3570.0],
            }
        )
        errors = validate_dataframe(df)
        assert len(errors) >= 3  # 保单号格式 + 比例越界 + 金额为空，且全部保留
        assert {error.field for error in errors} == {"保单号", "赔付比例", "报案金额"}

"""
对账引擎 — 测试套件

测试范围：
1. 全部一致场景
2. 部分异常场景
3. 边界场景
"""

from decimal import Decimal

import pandas as pd
import pytest

from insurance_audit.audit.reconciler import reconcile_dataframe
from insurance_audit.models.claim import AuditSummary


class TestReconcileDataFrame:
    """对账引擎测试"""

    @pytest.mark.unit
    def test_all_matched(self, sample_dataframe: pd.DataFrame) -> None:
        """全部一致"""
        result_df, summary = reconcile_dataframe(sample_dataframe)
        assert summary.matched_records == 3
        assert summary.unmatched_records == 0
        assert summary.match_rate == 100.0

    @pytest.mark.unit
    def test_report_columns(self, sample_dataframe: pd.DataFrame) -> None:
        """报告列完整性"""
        result_df, _ = reconcile_dataframe(sample_dataframe)
        expected_columns = {
            "保单号",
            "客户姓名",
            "报案金额",
            "免赔额",
            "赔付比例",
            "原始赔付金额",
            "系统核算金额",
            "差异金额",
            "审计状态",
        }
        assert expected_columns.issubset(set(result_df.columns))

    @pytest.mark.unit
    def test_partial_mismatch(self) -> None:
        """部分不一致"""
        df = pd.DataFrame(
            {
                "保单号": ["CL9900100", "CL9900101"],
                "客户姓名": ["张三", "李四"],
                "报案金额": [1000.0, 2000.0],
                "免赔额": [500.0, 500.0],
                "赔付比例": [0.80, 0.80],
                "实际赔付金额": [400.0, 9999.0],  # 第二条故意不一致
            }
        )
        result_df, summary = reconcile_dataframe(df)
        assert summary.matched_records == 1
        assert summary.unmatched_records == 1
        assert summary.match_rate == 50.0

    @pytest.mark.unit
    def test_empty_dataframe(self) -> None:
        """空DataFrame"""
        df = pd.DataFrame(
            columns=[
                "保单号",
                "客户姓名",
                "报案金额",
                "免赔额",
                "赔付比例",
                "实际赔付金额",
            ]
        )
        result_df, summary = reconcile_dataframe(df)
        assert summary.total_records == 0
        assert summary.match_rate == 0.0

    @pytest.mark.unit
    def test_audit_summary_type(self, sample_dataframe: pd.DataFrame) -> None:
        """审计摘要类型检查"""
        _, summary = reconcile_dataframe(sample_dataframe)
        assert isinstance(summary, AuditSummary)
        assert isinstance(summary.total_discrepancy, Decimal)

    @pytest.mark.unit
    def test_parse_errors_are_tracked_not_dropped(self) -> None:
        """解析失败的行要留痕，不能被静默丢掉"""
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
        result_df, summary = reconcile_dataframe(df)

        assert summary.source_records == 2
        assert summary.total_records == 1
        assert summary.parse_error_records == 1
        assert summary.parse_errors[0]["row"] == 3
        assert summary.parse_errors[0]["policy_id"] == "ABC123"

        # 对账明细里仍能看到这一行，状态为「解析失败」
        parse_rows = result_df[result_df["审计状态"] == "解析失败"]
        assert len(parse_rows) == 1
        assert parse_rows.iloc[0]["保单号"] == "ABC123"

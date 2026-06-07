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
            "保单号", "客户姓名", "报案金额", "免赔额",
            "赔付比例", "原始赔付金额", "系统核算金额",
            "差异金额", "审计状态",
        }
        assert expected_columns.issubset(set(result_df.columns))

    @pytest.mark.unit
    def test_partial_mismatch(self) -> None:
        """部分不一致"""
        df = pd.DataFrame({
            "保单号": ["CL9900100", "CL9900101"],
            "客户姓名": ["张三", "李四"],
            "报案金额": [1000.0, 2000.0],
            "免赔额": [500.0, 500.0],
            "赔付比例": [0.80, 0.80],
            "实际赔付金额": [400.0, 9999.0],  # 第二条故意不一致
        })
        result_df, summary = reconcile_dataframe(df)
        assert summary.matched_records == 1
        assert summary.unmatched_records == 1
        assert summary.match_rate == 50.0

    @pytest.mark.unit
    def test_empty_dataframe(self) -> None:
        """空DataFrame"""
        df = pd.DataFrame(columns=[
            "保单号", "客户姓名", "报案金额", "免赔额",
            "赔付比例", "实际赔付金额",
        ])
        result_df, summary = reconcile_dataframe(df)
        assert summary.total_records == 0
        assert summary.match_rate == 0.0

    @pytest.mark.unit
    def test_audit_summary_type(self, sample_dataframe: pd.DataFrame) -> None:
        """审计摘要类型检查"""
        _, summary = reconcile_dataframe(sample_dataframe)
        assert isinstance(summary, AuditSummary)
        assert isinstance(summary.total_discrepancy, Decimal)

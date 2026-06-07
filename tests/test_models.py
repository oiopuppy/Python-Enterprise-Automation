"""
数据模型 — 测试套件

测试范围：
1. ClaimRecord 创建与验证
2. calculate_payout 模型方法
3. reconcile 对账方法
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from insurance_audit.models.claim import ClaimRecord


class TestClaimRecord:
    """理赔记录模型测试"""

    @pytest.mark.unit
    def test_create_valid_record(self) -> None:
        """创建有效记录"""
        record = ClaimRecord(
            policy_id="CL9900100",
            customer_name="张三",
            claim_amount=Decimal("1000.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("400.00"),
        )
        assert record.policy_id == "CL9900100"
        assert record.customer_name == "张三"

    @pytest.mark.unit
    def test_claim_amount_must_be_positive(self) -> None:
        """报案金额必须大于0"""
        with pytest.raises(ValidationError):
            ClaimRecord(
                policy_id="CL9900100",
                customer_name="张三",
                claim_amount=Decimal("0"),  # 应为正数
                deductible=Decimal("500.00"),
                payout_ratio=Decimal("0.80"),
                actual_payout=Decimal("0.00"),
            )

    @pytest.mark.unit
    def test_invalid_policy_id_format(self) -> None:
        """保单号格式错误"""
        with pytest.raises(ValidationError):
            ClaimRecord(
                policy_id="ABC123",  # 不匹配 CL 开头格式
                customer_name="张三",
                claim_amount=Decimal("1000.00"),
                deductible=Decimal("500.00"),
                payout_ratio=Decimal("0.80"),
                actual_payout=Decimal("400.00"),
            )

    @pytest.mark.unit
    def test_calculate_payout_above_deductible(self) -> None:
        """金额高于免赔额"""
        record = ClaimRecord(
            policy_id="CL9900100",
            customer_name="张三",
            claim_amount=Decimal("1000.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("400.00"),
        )
        assert record.calculate_payout() == Decimal("400.00")

    @pytest.mark.unit
    def test_calculate_payout_below_deductible(self) -> None:
        """金额低于免赔额"""
        record = ClaimRecord(
            policy_id="CL9900100",
            customer_name="张三",
            claim_amount=Decimal("300.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("0.00"),
        )
        assert record.calculate_payout() == Decimal("0.00")

    @pytest.mark.unit
    def test_reconcile_matched(self) -> None:
        """对账一致"""
        record = ClaimRecord(
            policy_id="CL9900100",
            customer_name="张三",
            claim_amount=Decimal("1000.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("400.00"),
        )
        is_match, diff = record.reconcile()
        assert is_match
        assert diff < Decimal("0.005")

    @pytest.mark.unit
    def test_reconcile_mismatched(self) -> None:
        """对账不一致"""
        record = ClaimRecord(
            policy_id="CL9900100",
            customer_name="张三",
            claim_amount=Decimal("1000.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("500.00"),  # 与实际不符
        )
        is_match, diff = record.reconcile()
        assert not is_match
        assert diff > Decimal("0.005")

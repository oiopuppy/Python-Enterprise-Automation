"""
赔付计算引擎 — 全面测试套件

测试范围：
1. 正常计算（各种参数组合）
2. 边界条件（等于免赔额、巨额赔付）
3. 异常场景（负数、无效比例、超限）
4. 精度验证（ROUND_HALF_UP）
5. 批量计算
"""

from decimal import Decimal

import pytest

from insurance_audit.core.calculator import (
    batch_calculate,
    calculate_payout,
)
from insurance_audit.utils.exceptions import (
    ClaimAmountExceedsLimitError,
    InvalidDeductibleError,
    InvalidRatioError,
    NegativeClaimAmountError,
)


class TestCalculatePayout:
    """赔付计算函数测试"""

    # =========================================================================
    # 正常场景
    # =========================================================================

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "claim,deductible,ratio,expected",
        [
            (Decimal("1000"), Decimal("500"), Decimal("0.80"), Decimal("400.00")),
            (Decimal("1500"), Decimal("500"), Decimal("0.90"), Decimal("900.00")),
            (Decimal("3000"), Decimal("1000"), Decimal("0.75"), Decimal("1500.00")),
            (Decimal("500"), Decimal("200"), Decimal("1.00"), Decimal("300.00")),
            (Decimal("10000"), Decimal("0"), Decimal("0.50"), Decimal("5000.00")),
        ],
    )
    def test_normal_cases(
        self,
        claim: Decimal,
        deductible: Decimal,
        ratio: Decimal,
        expected: Decimal,
    ) -> None:
        """正常场景 — 各种参数组合"""
        result = calculate_payout(claim, deductible, ratio)
        assert result == expected, (
            f"calculate_payout({claim}, {deductible}, {ratio}) "
            f"= {result}, expected {expected}"
        )

    @pytest.mark.unit
    def test_uses_default_deductible(self) -> None:
        """使用默认免赔额"""
        result = calculate_payout(Decimal("1000"))
        # 默认免赔额 500，默认比例 0.80
        assert result == Decimal("400.00")

    @pytest.mark.unit
    def test_uses_default_ratio(self) -> None:
        """使用默认赔付比例"""
        result = calculate_payout(Decimal("1000"), deductible=Decimal("300"))
        assert result == Decimal("560.00")  # (1000-300)*0.80

    # =========================================================================
    # 边界条件
    # =========================================================================

    @pytest.mark.unit
    def test_claim_equals_deductible(self) -> None:
        """报案金额等于免赔额 — 赔付为0"""
        result = calculate_payout(Decimal("500"), Decimal("500"), Decimal("0.80"))
        assert result == Decimal("0.00")

    @pytest.mark.unit
    def test_claim_below_deductible(self) -> None:
        """报案金额低于免赔额 — 赔付为0"""
        result = calculate_payout(Decimal("300"), Decimal("500"), Decimal("0.80"))
        assert result == Decimal("0.00")

    @pytest.mark.unit
    def test_zero_deductible(self) -> None:
        """免赔额为0"""
        result = calculate_payout(Decimal("1000"), Decimal("0"), Decimal("0.80"))
        assert result == Decimal("800.00")

    @pytest.mark.unit
    def test_full_ratio(self) -> None:
        """全额赔付（比例=1.0）"""
        result = calculate_payout(Decimal("1000"), Decimal("500"), Decimal("1.00"))
        assert result == Decimal("500.00")

    @pytest.mark.unit
    def test_minimum_ratio(self) -> None:
        """最小赔付比例"""
        result = calculate_payout(Decimal("1000"), Decimal("500"), Decimal("0.01"))
        assert result == Decimal("5.00")

    # =========================================================================
    # 精度测试 — ROUND_HALF_UP
    # =========================================================================

    @pytest.mark.unit
    def test_round_half_up(self) -> None:
        """ROUND_HALF_UP 四舍五入验证"""
        # (100 - 0) * 0.335 = 33.5 -> 应舍入为 33.50 ✓
        result = calculate_payout(Decimal("100"), Decimal("0"), Decimal("0.335"))
        assert result == Decimal("33.50")

    @pytest.mark.unit
    def test_round_half_up_2(self) -> None:
        """ROUND_HALF_UP 四舍五入验证 - 进位"""
        # (100 - 0) * 0.336 = 33.6 -> 应舍入为 33.60 ✓
        result = calculate_payout(Decimal("100"), Decimal("0"), Decimal("0.336"))
        assert result == Decimal("33.60")

    # =========================================================================
    # 异常场景
    # =========================================================================

    @pytest.mark.unit
    def test_negative_claim_amount(self) -> None:
        """报案金额为负数"""
        with pytest.raises(NegativeClaimAmountError):
            calculate_payout(Decimal("-100"), Decimal("500"), Decimal("0.80"))

    @pytest.mark.unit
    def test_negative_deductible(self) -> None:
        """免赔额为负数"""
        with pytest.raises(InvalidDeductibleError):
            calculate_payout(Decimal("1000"), Decimal("-100"), Decimal("0.80"))

    @pytest.mark.unit
    def test_invalid_ratio_above_one(self) -> None:
        """赔付比例大于1"""
        with pytest.raises(InvalidRatioError):
            calculate_payout(Decimal("1000"), Decimal("500"), Decimal("1.50"))

    @pytest.mark.unit
    def test_invalid_ratio_negative(self) -> None:
        """赔付比例为负数"""
        with pytest.raises(InvalidRatioError):
            calculate_payout(Decimal("1000"), Decimal("500"), Decimal("-0.10"))

    @pytest.mark.unit
    def test_exceeds_annual_limit(self) -> None:
        """超过年度赔付上限"""
        with pytest.raises(ClaimAmountExceedsLimitError):
            calculate_payout(Decimal("999999"), Decimal("0"), Decimal("1.00"))


class TestBatchCalculate:
    """批量计算测试"""

    @pytest.mark.unit
    def test_batch_normal(self, sample_records: list) -> None:
        """批量正常计算"""
        results = batch_calculate(sample_records)
        assert len(results) == 3
        assert results[0].calculated_payout == Decimal("400.00")
        assert results[1].calculated_payout == Decimal("0.00")
        assert results[2].calculated_payout == Decimal("3570.00")

    @pytest.mark.unit
    def test_batch_empty(self) -> None:
        """空列表"""
        results = batch_calculate([])
        assert results == []

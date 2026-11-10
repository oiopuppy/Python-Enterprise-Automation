"""
赔付计算的属性测试（hypothesis）

逐例测试只能覆盖写下来的几种组合；这里用属性锁住不变量，让 hypothesis
随机生成金额/免赔额/比例，去撞边界（刚好相等、刚好进位、比例 0/1 等）：

1. 赔付永远 >= 0
2. 结果一定是 2 位小数
3. 报案金额 <= 免赔额时恒为 0
4. 与「先乘后 ROUND_HALF_UP」的公式直算完全一致
5. 比例越大，赔付不会变小（单调性）
6. 负数报案、越界比例会被拒绝
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from insurance_audit.core.calculator import calculate_payout
from insurance_audit.utils.exceptions import InvalidRatioError, NegativeClaimAmountError

# settings.insurance.annual_limit 默认 500000；超过会抛业务异常，这里贴着上限生成
_MAX_CLAIM = Decimal("500000")
_money = st.decimals(
    min_value=Decimal("0"), max_value=_MAX_CLAIM, places=2, allow_nan=False, allow_infinity=False
)
_ratio = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1"), places=4, allow_nan=False, allow_infinity=False
)


@pytest.mark.unit
@hypothesis_settings(max_examples=200, deadline=None)
@given(claim=_money, deductible=_money, ratio=_ratio)
def test_payout_invariants(claim: Decimal, deductible: Decimal, ratio: Decimal) -> None:
    """金额非负、两位小数、与公式直算一致、免赔覆盖时为 0"""
    payout = calculate_payout(claim_amount=claim, deductible=deductible, ratio=ratio)

    assert payout >= Decimal("0")
    assert payout == payout.quantize(Decimal("0.01"))

    if claim <= deductible:
        assert payout == Decimal("0.00")
    else:
        expected = ((claim - deductible) * ratio).quantize(
            Decimal("0.01"), rounding="ROUND_HALF_UP"
        )
        assert payout == expected


@pytest.mark.unit
@hypothesis_settings(max_examples=100, deadline=None)
@given(claim=_money, deductible=_money, ratio_low=_ratio, ratio_high=_ratio)
def test_payout_monotonic_in_ratio(
    claim: Decimal, deductible: Decimal, ratio_low: Decimal, ratio_high: Decimal
) -> None:
    """同一笔账，比例越高赔付不会更低（0 赔付区间除外）"""
    assume(ratio_low <= ratio_high)

    low = calculate_payout(claim_amount=claim, deductible=deductible, ratio=ratio_low)
    high = calculate_payout(claim_amount=claim, deductible=deductible, ratio=ratio_high)
    assert high >= low


@pytest.mark.unit
@hypothesis_settings(max_examples=50, deadline=None)
@given(
    claim=st.decimals(max_value=Decimal("-0.01"), places=2, allow_nan=False, allow_infinity=False)
)
def test_negative_claim_is_rejected(claim: Decimal) -> None:
    """负数报案金额必须被拒绝，不能算出负赔付"""
    with pytest.raises(NegativeClaimAmountError):
        calculate_payout(claim_amount=claim)


@pytest.mark.unit
@hypothesis_settings(max_examples=50, deadline=None)
@given(
    claim=_money,
    ratio=st.decimals(
        min_value=Decimal("1.0001"),
        max_value=Decimal("5"),
        places=4,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_ratio_above_one_is_rejected(claim: Decimal, ratio: Decimal) -> None:
    """比例必须落在 0~1；超过 1 直接拒绝，而不是算出超额赔付"""
    with pytest.raises(InvalidRatioError):
        calculate_payout(claim_amount=claim, deductible=Decimal("0"), ratio=ratio)

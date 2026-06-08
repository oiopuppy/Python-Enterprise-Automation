"""
赔付金额计算引擎 — Payout Calculation Engine

核心业务逻辑，使用 Decimal 确保金融级精度。
支持：
1. 基础赔付计算
2. 批量赔付计算
3. 年度限额检查
4. 业务规则验证
"""

from decimal import Decimal
from typing import Optional

from insurance_audit.models.claim import ClaimRecord
from insurance_audit.utils.config import settings
from insurance_audit.utils.exceptions import (
    ClaimAmountExceedsLimitError,
    InvalidDeductibleError,
    InvalidRatioError,
    NegativeClaimAmountError,
)
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_payout(
    claim_amount: Decimal,
    deductible: Optional[Decimal] = None,
    ratio: Optional[Decimal] = None,
    policy_id: str = "",
) -> Decimal:
    """
    核心赔付计算函数
    
    公式：应赔额 = (报案金额 - 免赔额) * 赔付比例
    当报案金额 <= 免赔额时，赔付为0
    
    Args:
        claim_amount: 报案金额（元）
        deductible: 免赔额（元），不传则使用全局默认值
        ratio: 赔付比例，不传则使用全局默认值
        policy_id: 保单号（可选，用于错误信息）
    
    Returns:
        计算结果（Decimal，2位小数，ROUND_HALF_UP）
    
    Raises:
        NegativeClaimAmountError: 报案金额为负数
        InvalidDeductibleError: 免赔额为负数
        InvalidRatioError: 赔付比例不在0~1之间
        ClaimAmountExceedsLimitError: 超过年度赔付上限
    """
    # --- 参数校验 ---
    if claim_amount < Decimal("0"):
        raise NegativeClaimAmountError(float(claim_amount))

    deductible = deductible if deductible is not None else settings.insurance.default_deductible
    ratio = ratio if ratio is not None else settings.insurance.default_ratio

    if deductible < Decimal("0"):
        raise InvalidDeductibleError(float(deductible))
    if not Decimal("0") <= ratio <= Decimal("1"):
        raise InvalidRatioError(float(ratio))

    # --- 年度限额检查 ---
    if claim_amount > settings.insurance.annual_limit:
        raise ClaimAmountExceedsLimitError(
            amount=float(claim_amount),
            limit=float(settings.insurance.annual_limit),
            policy_id=policy_id,
        )

    # --- 核心计算 ---
    if claim_amount <= deductible:
        logger.debug(
            f"报案金额 {claim_amount} <= 免赔额 {deductible}，赔付为0"
        )
        return Decimal("0.00")

    payout = (claim_amount - deductible) * ratio
    precision = Decimal(10) ** -settings.insurance.decimal_places
    result = payout.quantize(precision, rounding="ROUND_HALF_UP")

    logger.debug(
        f"赔付计算: 报案={claim_amount} 免赔={deductible} "
        f"比例={ratio} -> 赔付={result}"
    )
    return result


def batch_calculate(records: list[ClaimRecord]) -> list[ClaimRecord]:
    """
    批量赔付计算
    
    Args:
        records: 理赔记录列表
    
    Returns:
        计算完成后的记录列表（calculated_payout 字段已填充）
    """
    logger.info(f"开始批量赔付计算，共 {len(records)} 条记录")
    processed = 0
    errors = 0

    for record in records:
        try:
            record.calculated_payout = record.calculate_payout()
            processed += 1
        except Exception as e:
            errors += 1
            logger.error(
                f"计算失败 — 保单 {record.policy_id}: {e}"
            )
            record.calculated_payout = Decimal("0.00")

    logger.info(
        f"批量计算完成: 成功={processed}, 失败={errors}"
    )
    return records

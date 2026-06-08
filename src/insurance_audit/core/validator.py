"""
数据验证层 — Data Validation Layer

央企数据质量要求：
1. 非空校验
2. 数据类型校验
3. 业务规则校验
4. 精度校验
5. 完整性校验
"""

from decimal import Decimal
from typing import Any

import pandas as pd

from insurance_audit.utils.config import settings
from insurance_audit.utils.exceptions import (
    DataValidationError,
    InvalidColumnError,
)
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# 必选列定义（中文名 -> 字段说明）
REQUIRED_COLUMNS: dict[str, str] = {
    "保单号": "保单唯一编号",
    "客户姓名": "客户名称",
    "报案金额": "理赔报案金额（元）",
    "免赔额": "免赔额（元）",
    "赔付比例": "赔付比例（0~1）",
    "实际赔付金额": "原始表中已支付的赔付金额（元）",
}

# 金额列（需要 Decimal 精度处理）
MONEY_COLUMNS = {"报案金额", "免赔额", "实际赔付金额"}

# 数值范围约束
COLUMN_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "报案金额": {
        "min": settings.insurance.min_claim_amount,
        "max": settings.insurance.max_claim_amount,
    },
    "免赔额": {"min": Decimal("0"), "max": Decimal("99999999.99")},
    "赔付比例": {"min": Decimal("0"), "max": Decimal("1")},
    "实际赔付金额": {"min": Decimal("0"), "max": Decimal("99999999.99")},
}


def validate_columns(df: pd.DataFrame) -> None:
    """
    校验Excel文件是否包含所有必需的列
    
    Raises:
        InvalidColumnError: 缺少必需列
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise InvalidColumnError(missing)
    logger.debug(f"列校验通过，共 {len(df.columns)} 列")


def validate_row(
    row: tuple[int, dict[str, Any]],
) -> tuple[bool, str]:
    """
    校验单行数据
    
    Args:
        row: (行号, 行数据字典)
    
    Returns:
        (是否通过, 错误信息)
    """
    index, data = row
    row_num = index + 2  # Excel行号（+2 因为从0开始且表头占1行）

    # 1. 非空校验
    for col in REQUIRED_COLUMNS:
        value = data.get(col)
        if pd.isna(value) or value is None or str(value).strip() == "":
            return False, f"第{row_num}行 [{col}] 为空"

    # 2. 金额列校验
    for col in MONEY_COLUMNS:
        value = data.get(col)
        try:
            dec_val = Decimal(str(value))
        except Exception:
            return False, f"第{row_num}行 [{col}] 不是有效金额: {value}"

        constraints = COLUMN_CONSTRAINTS.get(col)
        if constraints:
            if dec_val < constraints["min"]:
                return False, (
                    f"第{row_num}行 [{col}] = {dec_val} "
                    f"低于最小值 {constraints['min']}"
                )
            if dec_val > constraints["max"]:
                return False, (
                    f"第{row_num}行 [{col}] = {dec_val} "
                    f"超过最大值 {constraints['max']}"
                )

        # 精度校验（最多2位小数）
        if dec_val.as_tuple().exponent < -2:
            return False, (
                f"第{row_num}行 [{col}] = {dec_val} "
                f"精度超过2位小数，不符合财务规范"
            )

    # 3. 赔付比例校验
    ratio = Decimal(str(data.get("赔付比例", 0)))
    if ratio < Decimal("0") or ratio > Decimal("1"):
        return False, f"第{row_num}行 [赔付比例] = {ratio} 不在0~1范围内"

    # 4. 保单号格式校验
    policy_id = str(data.get("保单号", ""))
    if not policy_id.startswith(settings.insurance.policy_prefix):
        return False, f"第{row_num}行 [保单号] = {policy_id} 格式异常（应以{settings.insurance.policy_prefix}开头）"

    return True, ""


def validate_dataframe(df: pd.DataFrame) -> list[DataValidationError]:
    """
    全量数据校验
    
    Args:
        df: 数据 DataFrame
    
    Returns:
        校验错误列表（空列表表示全部通过）
    """
    logger.info(f"开始数据校验，共 {len(df)} 行")
    
    # 1. 先校验列
    validate_columns(df)
    
    # 2. 逐行校验
    errors: list[DataValidationError] = []
    valid_count = 0

    for index, row_data in df.iterrows():
        is_valid, error_msg = validate_row((index, dict(row_data)))
        if is_valid:
            valid_count += 1
        else:
            errors.append(
                DataValidationError(
                    row_index=index + 2,
                    field="综合",
                    value="",
                    reason=error_msg,
                )
            )

    logger.info(
        f"数据校验完成: 有效={valid_count}, 异常={len(errors)}"
    )
    return errors

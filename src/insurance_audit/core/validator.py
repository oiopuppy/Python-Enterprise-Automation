"""
数据验证层：列校验与逐行质量校验

设计原则：
1. 一行里的问题要全部收集，不能遇到第一个就返回
2. 每个问题都带问题代码和具体字段名，便于筛选、统计与定位
3. 校验结果只作为数据质量提示，不阻断对账、不丢弃行
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

from insurance_audit.utils.config import settings
from insurance_audit.utils.exceptions import InvalidColumnError
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# 问题代码（报告与 JSON 共用，便于筛选和统计）
CODE_EMPTY = "EMPTY"
CODE_FORMAT = "FORMAT"
CODE_RANGE = "RANGE"
CODE_PRECISION = "PRECISION"
CODE_CROSS_FIELD = "CROSS_FIELD"
CODE_DUPLICATE_POLICY = "DUPLICATE_POLICY"
CODE_CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"

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


@dataclass(frozen=True)
class FieldIssue:
    """单条数据质量问题：行号、字段名、问题代码、说明、原始值"""

    row: int
    field: str
    code: str
    message: str
    value: str = ""


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
) -> list[FieldIssue]:
    """
    校验单行数据，返回该行的全部问题（不提前返回）

    Args:
        row: (行号, 行数据字典)

    Returns:
        问题列表（空列表表示该行没有发现问题）
    """
    index, data = row
    row_num = index + 2  # Excel行号（+2 因为从0开始且表头占1行）
    issues: list[FieldIssue] = []

    # 1. 非空校验：记录缺失列，后续跳过相关数值检查，避免同一格报两条
    missing: set[str] = set()
    for col in REQUIRED_COLUMNS:
        value = data.get(col)
        if pd.isna(value) or value is None or str(value).strip() == "":
            missing.add(col)
            issues.append(
                FieldIssue(
                    row=row_num,
                    field=col,
                    code=CODE_EMPTY,
                    message=f"第{row_num}行 [{col}] 为空",
                    value="",
                )
            )

    # 2. 金额列校验：解析、范围、精度
    parsed: dict[str, Decimal] = {}
    for col in MONEY_COLUMNS:
        if col in missing:
            continue
        value = data.get(col)
        try:
            dec_val = Decimal(str(value))
        except Exception:
            issues.append(
                FieldIssue(
                    row=row_num,
                    field=col,
                    code=CODE_FORMAT,
                    message=f"第{row_num}行 [{col}] 不是有效金额: {value}",
                    value=str(value),
                )
            )
            continue

        parsed[col] = dec_val
        constraints = COLUMN_CONSTRAINTS.get(col)
        if constraints:
            if dec_val < constraints["min"]:
                issues.append(
                    FieldIssue(
                        row=row_num,
                        field=col,
                        code=CODE_RANGE,
                        message=f"第{row_num}行 [{col}] = {dec_val} 低于最小值 {constraints['min']}",
                        value=str(dec_val),
                    )
                )
            elif dec_val > constraints["max"]:
                issues.append(
                    FieldIssue(
                        row=row_num,
                        field=col,
                        code=CODE_RANGE,
                        message=f"第{row_num}行 [{col}] = {dec_val} 超过最大值 {constraints['max']}",
                        value=str(dec_val),
                    )
                )

        exponent = dec_val.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            issues.append(
                FieldIssue(
                    row=row_num,
                    field=col,
                    code=CODE_PRECISION,
                    message=f"第{row_num}行 [{col}] = {dec_val} 精度超过2位小数，不符合财务规范",
                    value=str(dec_val),
                )
            )

    # 3. 赔付比例校验
    if "赔付比例" not in missing:
        raw_ratio = data.get("赔付比例")
        try:
            ratio = Decimal(str(raw_ratio))
        except Exception:
            issues.append(
                FieldIssue(
                    row=row_num,
                    field="赔付比例",
                    code=CODE_FORMAT,
                    message=f"第{row_num}行 [赔付比例] 不是有效数值: {raw_ratio}",
                    value=str(raw_ratio),
                )
            )
        else:
            if ratio < Decimal("0") or ratio > Decimal("1"):
                issues.append(
                    FieldIssue(
                        row=row_num,
                        field="赔付比例",
                        code=CODE_RANGE,
                        message=f"第{row_num}行 [赔付比例] = {ratio} 不在0~1范围内",
                        value=str(ratio),
                    )
                )

    # 4. 保单号格式校验
    if "保单号" not in missing:
        policy_id = str(data.get("保单号", "")).strip()
        if not policy_id.startswith(settings.insurance.policy_prefix):
            issues.append(
                FieldIssue(
                    row=row_num,
                    field="保单号",
                    code=CODE_FORMAT,
                    message=(
                        f"第{row_num}行 [保单号] = {policy_id} "
                        f"格式异常（应以{settings.insurance.policy_prefix}开头）"
                    ),
                    value=policy_id,
                )
            )

    # 5. 跨字段业务规则（只作为数据质量提示，不阻断对账、不丢弃该行）
    claim_amount = parsed.get("报案金额")
    deductible = parsed.get("免赔额")
    actual_payout = parsed.get("实际赔付金额")
    if claim_amount is not None and actual_payout is not None and actual_payout > claim_amount:
        issues.append(
            FieldIssue(
                row=row_num,
                field="实际赔付金额",
                code=CODE_CROSS_FIELD,
                message=(f"第{row_num}行 实际赔付金额 {actual_payout} 超过报案金额 {claim_amount}"),
                value=str(actual_payout),
            )
        )
    if (
        claim_amount is not None
        and deductible is not None
        and actual_payout is not None
        and claim_amount <= deductible
        and actual_payout != Decimal("0")
    ):
        issues.append(
            FieldIssue(
                row=row_num,
                field="实际赔付金额",
                code=CODE_CROSS_FIELD,
                message=(
                    f"第{row_num}行 报案金额未超过免赔额，实际赔付应为 0，实际为 {actual_payout}"
                ),
                value=str(actual_payout),
            )
        )

    return issues


def find_duplicate_issues(df: pd.DataFrame) -> list[FieldIssue]:
    """
    跨行一致性检查：重复保单号、同一保单号对应不同客户名

    重复行本身不删除、不合并，照常参与对账；这里只负责把问题标记出来。
    """
    if df.empty or "保单号" not in df.columns:
        return []

    issues: list[FieldIssue] = []
    policy_series = df["保单号"].astype(str).str.strip()

    for policy_id, group in df.groupby(policy_series, sort=False):
        if policy_id in ("", "nan", "None"):
            continue
        if len(group) < 2:
            continue

        rows = [int(idx) + 2 for idx in group.index]
        rows_text = "、".join(str(row) for row in rows)

        total_payout = Decimal("0.00")
        if "实际赔付金额" in df.columns:
            for value in group["实际赔付金额"]:
                try:
                    total_payout += Decimal(str(value))
                except Exception:
                    logger.debug(f"重复保单金额合计时跳过非数值: {value}")
                    continue

        issues.append(
            FieldIssue(
                row=rows[0],
                field="保单号",
                code=CODE_DUPLICATE_POLICY,
                message=(
                    f"保单号 {policy_id} 重复出现 {len(rows)} 次"
                    f"（第 {rows_text} 行），实际赔付合计 {total_payout}"
                ),
                value=policy_id,
            )
        )

        if "客户姓名" in df.columns:
            names = {
                str(name).strip()
                for name in group["客户姓名"]
                if not pd.isna(name) and str(name).strip()
            }
            if len(names) > 1:
                issues.append(
                    FieldIssue(
                        row=rows[0],
                        field="客户姓名",
                        code=CODE_CUSTOMER_MISMATCH,
                        message=(
                            f"保单号 {policy_id} 在不同行对应多个客户名："
                            f"{'、'.join(sorted(names))}（第 {rows_text} 行）"
                        ),
                        value=policy_id,
                    )
                )

    return issues


def validate_dataframe(df: pd.DataFrame) -> list[FieldIssue]:
    """
    全量数据校验（逐行问题 + 跨行重复）

    Args:
        df: 数据 DataFrame

    Returns:
        校验问题列表（空列表表示全部通过）
    """
    logger.info(f"开始数据校验，共 {len(df)} 行")

    # 1. 先校验列
    validate_columns(df)

    # 2. 逐行校验：一行可能产生多条问题
    issues: list[FieldIssue] = []
    for index, row_data in df.iterrows():
        issues.extend(validate_row((index, dict(row_data))))

    # 3. 跨行一致性检查
    issues.extend(find_duplicate_issues(df))

    duplicated_rows = sum(1 for issue in issues if issue.code == CODE_DUPLICATE_POLICY)
    logger.info(f"数据校验完成: 问题={len(issues)} 条，其中重复保单组={duplicated_rows}")
    return issues

"""
自动对账引擎 — Automated Reconciliation Engine

功能：
1. 批量赔付计算
2. 系统核算 vs 原始数据对比
3. 差异分析
4. 审计状态标注

数据完整性约定：无法解析的行不会被静默丢弃，而是记入
``AuditSummary.parse_errors`` 并以「解析失败」状态写进对账明细，
保证「读取行数 = 成功解析行数 + 解析失败行数」。
"""

from decimal import Decimal
from typing import Any, Union

import pandas as pd

from insurance_audit.models.claim import AuditSummary, ClaimRecord
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# 无法解析的记录在对账明细里的统一状态
PARSE_ERROR_STATUS = "解析失败"


def _build_record_dict(row: pd.Series) -> dict[str, Union[Decimal, str]]:
    """把一行 DataFrame 数据转成 ClaimRecord 需要的字段字典"""
    return {
        "保单号": str(row["保单号"]),
        "客户姓名": str(row["客户姓名"]),
        "报案金额": Decimal(str(row["报案金额"])),
        "免赔额": Decimal(str(row["免赔额"])),
        "赔付比例": Decimal(str(row["赔付比例"])),
        "实际赔付金额": Decimal(str(row["实际赔付金额"])),
    }


def reconcile_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, AuditSummary]:
    """
    对账处理：逐行计算 -> 对比 -> 标注状态

    Args:
        df: 输入数据 DataFrame（必须包含保单号、报案金额、免赔额、赔付比例、实际赔付金额列）

    Returns:
        (标注后的 DataFrame, 审计摘要)

    Raises:
        SystemException: 读取或解析过程中出现非数据类异常时向上抛出，
            避免把系统故障伪装成「数据有问题」。
    """
    # 空DataFrame前置检查
    if df.empty:
        logger.warning("输入DataFrame为空，无数据可对账")
        empty_summary = AuditSummary(
            source_records=0,
            total_records=0,
            matched_records=0,
            unmatched_records=0,
            match_rate=0.0,
            total_claim_amount=Decimal("0.00"),
            total_actual_payout=Decimal("0.00"),
            total_calculated_payout=Decimal("0.00"),
            total_discrepancy=Decimal("0.00"),
            details=[],
        )
        return df, empty_summary

    logger.info(f"开始自动对账，共 {len(df)} 条记录")

    # 转换 DataFrame 为 ClaimRecord 列表；解析失败逐条留痕，不再静默跳过
    records: list[ClaimRecord] = []
    parse_errors: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        try:
            records.append(ClaimRecord.model_validate(_build_record_dict(row)))
        except (ValueError, ArithmeticError) as e:  # 数据格式/数值转换错误
            parse_errors.append(
                {
                    "row": idx + 2,  # Excel 行号：表头占第 1 行
                    "policy_id": str(row.get("保单号", "")),
                    "reason": str(e),
                }
            )
            logger.error(f"第 {idx + 2} 行无法解析，已记入异常数据: {e}")

    if parse_errors:
        logger.error(f"解析失败 {len(parse_errors)} 条记录，已单独记入报告「异常数据」")

    # 执行对账
    matched = 0
    unmatched = 0
    total_discrepancy = Decimal("0.00")
    total_calculated = Decimal("0.00")
    total_actual = Decimal("0.00")
    detail_rows: list[dict[str, Any]] = []

    for record in records:
        is_match, diff = record.reconcile()
        total_calculated += record.calculated_payout or Decimal("0.00")
        total_actual += record.actual_payout
        total_discrepancy += diff

        if is_match:
            matched += 1
        else:
            unmatched += 1
            logger.warning(
                f"对账差异 — {record.policy_id}: "
                f"核算={record.calculated_payout} "
                f"原始={record.actual_payout} "
                f"差异={diff}"
            )

        detail_rows.append(
            {
                "保单号": record.policy_id,
                "客户姓名": record.customer_name,
                "报案金额": float(record.claim_amount),
                "免赔额": float(record.deductible),
                "赔付比例": float(record.payout_ratio),
                "原始赔付金额": float(record.actual_payout),
                "系统核算金额": float(record.calculated_payout or Decimal("0.00")),
                "差异金额": float(diff),
                "审计状态": record.audit_status or "",
            }
        )

    # 无法解析的行同样进入明细，保证报告里能看到「少掉的那几行」
    for err in parse_errors:
        detail_rows.append(
            {
                "保单号": str(err["policy_id"]),
                "客户姓名": "",
                "报案金额": None,
                "免赔额": None,
                "赔付比例": None,
                "原始赔付金额": None,
                "系统核算金额": None,
                "差异金额": None,
                "审计状态": PARSE_ERROR_STATUS,
            }
        )

    # 构建结果 DataFrame
    result_df = pd.DataFrame(detail_rows)

    # 构建审计摘要
    summary = AuditSummary(
        source_records=len(df),
        total_records=len(records),
        parse_error_records=len(parse_errors),
        parse_errors=parse_errors,
        matched_records=matched,
        unmatched_records=unmatched,
        match_rate=round(matched / len(records) * 100 if records else 0.0, 2),
        total_claim_amount=sum((r.claim_amount for r in records), start=Decimal("0.00")),
        total_actual_payout=total_actual,
        total_calculated_payout=total_calculated,
        total_discrepancy=total_discrepancy,
        details=detail_rows,
    )

    logger.info(
        f"对账完成: 读取={summary.source_records}, "
        f"解析成功={summary.total_records}, "
        f"解析失败={summary.parse_error_records}, "
        f"一致={summary.matched_records}, "
        f"异常={summary.unmatched_records}, "
        f"一致率={summary.match_rate}%"
    )

    return result_df, summary

"""
自动对账引擎 — Automated Reconciliation Engine

功能：
1. 批量赔付计算
2. 系统核算 vs 原始数据对比
3. 差异分析
4. 审计状态标注
"""

from decimal import Decimal

import pandas as pd

from insurance_audit.core.calculator import calculate_payout
from insurance_audit.models.claim import AuditSummary, ClaimRecord
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)


def reconcile_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, AuditSummary]:
    """
    对账处理：逐行计算 -> 对比 -> 标注状态
    
    Args:
        df: 输入数据 DataFrame（必须包含保单号、报案金额、免赔额、赔付比例、实际赔付金额列）
    
    Returns:
        (标注后的 DataFrame, 审计摘要)
    """
    # 空DataFrame前置检查
    if df.empty:
        logger.warning("输入DataFrame为空，无数据可对账")
        empty_summary = AuditSummary(
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

    # 转换 DataFrame 为 ClaimRecord 列表
    records: list[ClaimRecord] = []
    parse_errors = 0
    for idx, row in df.iterrows():
        try:
            record = ClaimRecord(
                policy_id=str(row["保单号"]),
                customer_name=str(row["客户姓名"]),
                claim_amount=Decimal(str(row["报案金额"])),
                deductible=Decimal(str(row["免赔额"])),
                payout_ratio=Decimal(str(row["赔付比例"])),
                actual_payout=Decimal(str(row["实际赔付金额"])),
            )
            records.append(record)
        except Exception as e:
            parse_errors += 1
            logger.warning(f"第 {idx + 2} 行解析失败: {e}")

    if parse_errors:
        logger.warning(f"解析失败 {parse_errors} 条记录，已跳过")

    # 执行对账
    matched = 0
    unmatched = 0
    total_discrepancy = Decimal("0.00")
    total_calculated = Decimal("0.00")
    total_actual = Decimal("0.00")
    detail_rows: list[dict] = []

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

        detail_rows.append({
            "保单号": record.policy_id,
            "客户姓名": record.customer_name,
            "报案金额": str(record.claim_amount),
            "免赔额": str(record.deductible),
            "赔付比例": str(record.payout_ratio),
            "原始赔付金额": str(record.actual_payout),
            "系统核算金额": str(record.calculated_payout or Decimal("0.00")),
            "差异金额": str(diff),
            "审计状态": record.audit_status or "",
        })

    # 构建结果 DataFrame
    result_df = pd.DataFrame(detail_rows)

    # 构建审计摘要
    summary = AuditSummary(
        total_records=len(records),
        matched_records=matched,
        unmatched_records=unmatched,
        match_rate=round(
            matched / len(records) * 100 if records else 0, 2
        ),
        total_claim_amount=sum(
            r.claim_amount for r in records
        ),
        total_actual_payout=total_actual,
        total_calculated_payout=total_calculated,
        total_discrepancy=total_discrepancy,
        details=detail_rows,
    )

    logger.info(
        f"对账完成: 总计={summary.total_records}, "
        f"一致={summary.matched_records}, "
        f"异常={summary.unmatched_records}, "
        f"一致率={summary.match_rate}%"
    )

    return result_df, summary

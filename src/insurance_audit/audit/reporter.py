"""
审计报告生成器 — Audit Report Generator

生成结构化审计报告，包括：
1. 详细对账结果
2. 审计摘要
3. 异常数据明细
4. 统计汇总
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from insurance_audit.models.claim import AuditSummary
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)


def generate_report(
    detail_df: pd.DataFrame,
    summary: AuditSummary,
    output_path: str | Path,
) -> Path:
    """
    生成完整的审计报告 Excel 文件（多Sheet）
    
    报告结构：
    - Sheet 1: 审计摘要
    - Sheet 2: 对账明细
    - Sheet 3: 异常数据
    
    Args:
        detail_df: 对账明细 DataFrame
        summary: 审计摘要
        output_path: 输出文件路径
    
    Returns:
        输出文件的绝对路径
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # --- Sheet 1: 审计摘要 ---
    summary_data = {
        "审计项目": [
            "审计时间",
            "数据总量",
            "一致记录数",
            "异常记录数",
            "一致率",
            "总报案金额",
            "总原始赔付",
            "总系统核算",
            "总差异金额",
        ],
        "数值": [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(summary.total_records),
            str(summary.matched_records),
            str(summary.unmatched_records),
            f"{summary.match_rate}%",
            f"¥{summary.total_claim_amount:,.2f}",
            f"¥{summary.total_actual_payout:,.2f}",
            f"¥{summary.total_calculated_payout:,.2f}",
            f"¥{summary.total_discrepancy:,.2f}",
        ],
    }
    summary_df = pd.DataFrame(summary_data)

    # --- Sheet 3: 异常数据 ---
    if summary.unmatched_records > 0:
        anomaly_df = detail_df[detail_df["审计状态"] == "异常"].copy()
    else:
        anomaly_df = pd.DataFrame(columns=detail_df.columns)

    # --- 写入 Excel ---
    with pd.ExcelWriter(
        str(path.absolute()),
        engine="openpyxl",
    ) as writer:
        summary_df.to_excel(
            writer, sheet_name="审计摘要", index=False
        )
        detail_df.to_excel(
            writer, sheet_name="对账明细", index=False
        )
        anomaly_df.to_excel(
            writer, sheet_name="异常数据", index=False
        )

        # 自动调整列宽（所有Sheet）
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = max(
                    len(str(cell.value or "")) for cell in column
                )
                worksheet.column_dimensions[
                    column[0].column_letter
                ].width = min(max_length + 4, 50)

    abs_path = path.absolute()
    size_kb = path.stat().st_size / 1024
    logger.info(f"审计报告已生成: {abs_path} ({size_kb:.1f} KB)")
    logger.info(f"  报告包含 {len(detail_df)} 条明细 + {summary.unmatched_records} 条异常标记")
    
    return abs_path

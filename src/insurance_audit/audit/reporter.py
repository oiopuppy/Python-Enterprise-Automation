"""
审计报告生成器 — Audit Report Generator

生成结构化审计报告，包括：
1. 审计摘要（含数据完整性统计）
2. 详细对账结果
3. 异常数据明细（含无法解析的行）
4. 数据质量问题（字段级校验结果）
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from insurance_audit import __version__
from insurance_audit.audit.reconciler import PARSE_ERROR_STATUS
from insurance_audit.core.validator import (
    CODE_CUSTOMER_MISMATCH,
    CODE_DUPLICATE_POLICY,
    FieldIssue,
)
from insurance_audit.data.writer import auto_adjust_column_width
from insurance_audit.models.claim import AuditSummary
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# 视为异常、需要人工复核的审计状态
ANOMALY_STATUSES = ("异常", PARSE_ERROR_STATUS)

# 对账明细中按金额显示的列（静态格式，便于在 Excel 里直接求和）
DETAIL_AMOUNT_COLUMNS = ("报案金额", "免赔额", "原始赔付金额", "系统核算金额", "差异金额")
# 对账明细中按比例显示的列
DETAIL_RATIO_COLUMNS = ("赔付比例",)


def _build_summary_rows(summary: AuditSummary) -> list[tuple[str, object, str]]:
    """构造审计摘要的三列表格：项目 / 数值 / 单位"""
    return [
        ("审计时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""),
        ("读取总行数", summary.source_records, "条"),
        ("成功解析", summary.total_records, "条"),
        ("无法解析", summary.parse_error_records, "条"),
        ("重复保单组数", summary.duplicate_policy_groups, "组"),
        ("一致记录数", summary.matched_records, "条"),
        ("异常记录数", summary.unmatched_records, "条"),
        ("一致率", summary.match_rate, "%"),
        ("总报案金额", float(summary.total_claim_amount), "元"),
        ("总原始赔付", float(summary.total_actual_payout), "元"),
        ("总系统核算", float(summary.total_calculated_payout), "元"),
        ("总差异金额", float(summary.total_discrepancy), "元"),
    ]


def _build_quality_rows(
    validation_issues: list[FieldIssue],
    summary: AuditSummary,
) -> list[dict[str, object]]:
    """构造数据质量问题明细：字段问题 + 重复保单/跨行问题 + 无法解析记录"""
    rows: list[dict[str, object]] = []
    for issue in validation_issues:
        if issue.code == CODE_DUPLICATE_POLICY:
            issue_type = "重复保单"
        elif issue.code == CODE_CUSTOMER_MISMATCH:
            issue_type = "跨行不一致"
        else:
            issue_type = "字段校验"
        rows.append(
            {
                "问题类型": issue_type,
                "问题代码": issue.code,
                "行号": issue.row,
                "字段": issue.field,
                "原因": issue.message,
            }
        )
    for parse_err in summary.parse_errors:
        rows.append(
            {
                "问题类型": "无法解析",
                "问题代码": "PARSE_ERROR",
                "行号": parse_err.get("row", ""),
                "字段": "整行",
                "原因": parse_err.get("reason", ""),
            }
        )
    return rows


def _apply_detail_formats(ws: Any, df: pd.DataFrame) -> None:
    """给对账明细/异常数据的金额列、比例列设置 Excel 数字格式"""
    columns = list(df.columns)
    for col in DETAIL_AMOUNT_COLUMNS:
        if col not in columns:
            continue
        idx = columns.index(col) + 1
        for row in range(2, len(df) + 2):
            ws.cell(row=row, column=idx).number_format = "#,##0.00"
    for col in DETAIL_RATIO_COLUMNS:
        if col not in columns:
            continue
        idx = columns.index(col) + 1
        for row in range(2, len(df) + 2):
            # 存 0.8，显示 80.00% —— 既方便阅读又不破坏数值语义
            ws.cell(row=row, column=idx).number_format = "0.00%"


def _sha256(path: Union[str, Path]) -> str:
    """计算输入文件的 SHA-256，用于审计留痕；读不了时返回空串"""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def build_json_payload(
    summary: AuditSummary,
    input_file: str = "",
    output_file: str = "",
    validation_errors: Optional[list[FieldIssue]] = None,
) -> dict[str, Any]:
    """
    构造机器可读摘要（``--json`` 输出到 stdout、``--json-out`` 落盘共用）。

    金额一律用字符串，避免经过浮点后丢精度；明细不写入 JSON（避免大文件），
    完整明细见 Excel 的「对账明细」sheet。
    """
    quality_issues: list[dict[str, Any]] = []
    for issue in validation_errors or []:
        quality_issues.append(
            {
                "row": issue.row,
                "field": issue.field,
                "code": issue.code,
                "reason": issue.message,
            }
        )

    return {
        "tool_version": __version__,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input": {
            "path": input_file,
            "rows": summary.source_records,
            "sha256": _sha256(input_file) if input_file else "",
        },
        "output": {"path": output_file},
        "summary": {
            "source_records": summary.source_records,
            "total_records": summary.total_records,
            "parse_error_records": summary.parse_error_records,
            "matched_records": summary.matched_records,
            "unmatched_records": summary.unmatched_records,
            "match_rate": summary.match_rate,
            "total_claim_amount": str(summary.total_claim_amount),
            "total_actual_payout": str(summary.total_actual_payout),
            "total_calculated_payout": str(summary.total_calculated_payout),
            "total_discrepancy": str(summary.total_discrepancy),
        },
        "parse_errors": summary.parse_errors,
        "quality_issues": quality_issues,
        "execution_time": summary.execution_time,
    }


def write_json_report(
    payload: dict[str, Any],
    output_path: Union[str, Path],
) -> Path:
    """把 JSON 摘要写入文件（供 ``--json-out`` 使用）"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    abs_path = path.absolute()
    logger.info(f"JSON 摘要已生成: {abs_path}")
    return abs_path


def generate_report(
    detail_df: pd.DataFrame,
    summary: AuditSummary,
    output_path: Union[str, Path],
    validation_errors: Optional[list[FieldIssue]] = None,
) -> Path:
    """
    生成完整的审计报告 Excel 文件（多Sheet）

    报告结构：
    - Sheet 1: 审计摘要（含读取/解析/对账行数，保证行数可核对）
    - Sheet 2: 对账明细（解析失败的行也在内，状态为「解析失败」）
    - Sheet 3: 异常数据（对账异常 + 解析失败）
    - Sheet 4: 数据质量问题（字段级问题 + 重复保单/跨行问题 + 无法解析，可能为空）

    Args:
        detail_df: 对账明细 DataFrame
        summary: 审计摘要
        output_path: 输出文件路径
        validation_errors: 可选的数据质量问题列表

    Returns:
        输出文件的绝对路径
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # --- Sheet 1: 审计摘要 ---
    summary_rows = _build_summary_rows(summary)
    summary_df = pd.DataFrame(
        summary_rows,
        columns=["审计项目", "数值", "单位"],
    )

    # --- Sheet 2: 对账明细 ---
    detail_sheet_df = detail_df

    # --- Sheet 3: 异常数据（对账异常 + 解析失败）---
    if "审计状态" in detail_df.columns:
        anomaly_df = detail_df[detail_df["审计状态"].isin(ANOMALY_STATUSES)].copy()
    else:
        anomaly_df = pd.DataFrame(columns=[*detail_df.columns, "审计状态"])

    # --- Sheet 4: 数据质量问题 ---
    quality_rows = _build_quality_rows(validation_errors or [], summary)
    quality_df = pd.DataFrame(
        quality_rows,
        columns=["问题类型", "问题代码", "行号", "字段", "原因"],
    )

    # --- 写入 Excel ---
    with pd.ExcelWriter(str(path.absolute()), engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="审计摘要", index=False)
        detail_sheet_df.to_excel(writer, sheet_name="对账明细", index=False)
        anomaly_df.to_excel(writer, sheet_name="异常数据", index=False)
        quality_df.to_excel(writer, sheet_name="数据质量问题", index=False)
        auto_adjust_column_width(writer)

        # 明细里的金额与比例写成数值单元格，方便在 Excel 里直接筛选、求和
        _apply_detail_formats(writer.sheets["对账明细"], detail_df)
        if not anomaly_df.empty:
            _apply_detail_formats(writer.sheets["异常数据"], anomaly_df)

        # 摘要 Sheet：金额与百分比用 Excel 数字格式，保持可计算
        summary_ws = writer.sheets["审计摘要"]
        for offset, (_, _, unit) in enumerate(summary_rows):
            cell = summary_ws.cell(row=offset + 2, column=2)
            if unit == "元":
                cell.number_format = "#,##0.00"
            elif unit == "%":
                cell.number_format = '0.00"%"'

    abs_path = path.absolute()
    size_kb = path.stat().st_size / 1024
    logger.info(f"审计报告已生成: {abs_path} ({size_kb:.1f} KB)")
    logger.info(
        f"  报告包含 {len(detail_df)} 条明细（其中解析失败 {summary.parse_error_records} 条）"
        f" + {len(anomaly_df)} 条异常 + {len(quality_df)} 条数据质量问题"
    )

    return abs_path

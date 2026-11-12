"""
审计引擎 — 完整的工作流编排

将各个模块串联为可复用的审计流程。
支持编程式调用 vs CLI 调用两种模式。
"""

import json
import time
from typing import Any, Optional

from insurance_audit.audit.manifest import build_manifest
from insurance_audit.audit.reconciler import reconcile_dataframe
from insurance_audit.audit.reporter import generate_report
from insurance_audit.core.validator import (
    CODE_DUPLICATE_POLICY,
    FieldIssue,
    normalize_columns,
    validate_dataframe,
)
from insurance_audit.data.reader import read_excel
from insurance_audit.models.claim import AuditSummary
from insurance_audit.utils.config import settings
from insurance_audit.utils.logger import get_audit_logger, get_logger

logger = get_logger(__name__)


class AuditEngine:
    """
    审计引擎 — 完整工作流支持

    提供编程式调用：
        engine = AuditEngine()
        summary = engine.run()
    """

    def __init__(
        self,
        input_file: Optional[str] = None,
        output_file: Optional[str] = None,
    ) -> None:
        self.input_file = input_file or str(settings.data.input_path)
        self.output_file = output_file or str(settings.data.output_path)
        self.summary: Optional[AuditSummary] = None
        # 字段级校验问题：供 --json 的 quality_issues 使用
        self.validation_errors: list[FieldIssue] = []
        # 审计留痕清单：输入哈希、版本与生效配置
        self.manifest: Optional[dict[str, Any]] = None

    def run(self) -> AuditSummary:
        """
        执行完整审计流程

        Returns:
            审计摘要
        """
        logger.info("审计引擎启动 — 执行完整工作流")
        started = time.perf_counter()

        # 1. 读取数据（先把别名表头归一成标准列名）
        df = normalize_columns(read_excel(self.input_file))
        manifest = build_manifest(self.input_file, rows=len(df), output_path=self.output_file)
        self.manifest = manifest

        # 2. 数据校验
        validation_errors = validate_dataframe(df)
        self.validation_errors = validation_errors
        if validation_errors:
            logger.warning(f"数据校验发现 {len(validation_errors)} 个问题，已写入报告")

        # 3. 执行对账
        result_df, summary = reconcile_dataframe(df)
        summary.execution_time = f"{time.perf_counter() - started:.2f}s"
        summary.duplicate_policy_groups = sum(
            1 for issue in validation_errors if issue.code == CODE_DUPLICATE_POLICY
        )
        self.summary = summary

        # 4. 生成报告
        generate_report(
            result_df,
            summary,
            self.output_file,
            validation_errors=validation_errors,
            manifest=manifest,
        )

        # 5. 审计留痕：记录本次审计的输入指纹与关键配置
        get_audit_logger().safe_log(
            "AUDIT_COMPLETE",
            json.dumps(
                {
                    "input": manifest["input"],
                    "output": manifest.get("output"),
                    "tool_version": manifest["tool_version"],
                    "config": manifest["config"],
                    "summary": {
                        "source_records": summary.source_records,
                        "matched_records": summary.matched_records,
                        "unmatched_records": summary.unmatched_records,
                        "parse_error_records": summary.parse_error_records,
                    },
                },
                ensure_ascii=False,
            ),
        )

        logger.info("审计引擎工作流完成")
        return summary

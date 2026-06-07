"""
审计引擎 — 完整的工作流编排

将各个模块串联为可复用的审计流程。
支持编程式调用 vs CLI 调用两种模式。
"""

from insurance_audit.audit.reconciler import reconcile_dataframe
from insurance_audit.audit.reporter import generate_report
from insurance_audit.core.validator import validate_dataframe
from insurance_audit.data.reader import read_excel
from insurance_audit.models.claim import AuditSummary
from insurance_audit.utils.config import settings
from insurance_audit.utils.logger import get_logger

import pandas as pd

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
        input_file: str | None = None,
        output_file: str | None = None,
    ) -> None:
        self.input_file = input_file or str(settings.data.input_path)
        self.output_file = output_file or str(settings.data.output_path)
        self.summary: AuditSummary | None = None

    def run(self) -> AuditSummary:
        """
        执行完整审计流程
        
        Returns:
            审计摘要
        """
        logger.info("审计引擎启动 — 执行完整工作流")

        # 1. 读取数据
        df = read_excel(self.input_file)

        # 2. 数据校验
        validation_errors = validate_dataframe(df)
        if validation_errors:
            logger.warning(
                f"数据校验发现 {len(validation_errors)} 个问题，继续执行"
            )

        # 3. 执行对账
        result_df, summary = reconcile_dataframe(df)
        self.summary = summary

        # 4. 生成报告
        generate_report(result_df, summary, self.output_file)

        logger.info("审计引擎工作流完成")
        return summary

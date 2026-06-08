"""
保险理赔数据自动化审计系统 — 主入口
Enterprise Insurance Claim Audit System — Entry Point

工作流：
1. 加载配置
2. 健康检查（环境、文件就绪）
3. 读取数据
4. 数据校验
5. 自动对账
6. 生成报告
7. 审计追溯
"""

import sys
from decimal import Decimal

from insurance_audit import __app_name__, __version__
from insurance_audit.audit.reconciler import reconcile_dataframe
from insurance_audit.audit.reporter import generate_report
from insurance_audit.core.validator import validate_columns, validate_dataframe
from insurance_audit.data.generator import generate_mock_data
from insurance_audit.data.reader import read_excel
from insurance_audit.data.writer import write_excel
from insurance_audit.utils.config import settings
from insurance_audit.utils.exceptions import (
    DataException,
    InsuranceAuditError,
    SecurityException,
    SystemException,
)
from insurance_audit.utils.logger import audit_logger, get_logger

logger = get_logger(__name__)


# =============================================================================
# 阶段 1：环境健康检查
# =============================================================================

def check_environment() -> bool:
    """
    执行环境健康检查
    
    检查项：
    - 数据文件是否存在
    - 日志目录是否可写
    - 依赖是否就绪（通过启动时验证）
    """
    logger.info("=" * 60)
    logger.info(f"--- {__app_name__} v{__version__} ---")
    logger.info(f"执行环境: {settings.app.env}")
    logger.info(f"数据文件: {settings.data.input_path.name}")
    logger.info(f"输出目录: {settings.data.output_dir}")
    logger.info(f"审计模式: {'开启' if settings.app.is_production else '开发'}")
    logger.info("=" * 60)

    input_path = settings.data.input_path
    if not input_path.exists():
        logger.warning(
            f"数据文件不存在: {input_path.name}\n"
            f"  建议运行: python -m insurance_audit.data.generator 生成模拟数据"
        )
        return False

    logger.info(f"✅ 数据文件就绪: {input_path.name}")
    return True


# =============================================================================
# 阶段 2：审计执行
# =============================================================================

def run_audit() -> int:
    """
    执行完整的审计工作流
    
    Returns:
        0 = 全部对账一致, 1 = 存在对账异常
    """
    audit_logger.safe_log("AUDIT_START", "开始执行理赔数据审计流程")

    # --- 2a. 读取数据 ---
    logger.info("\n📂 [阶段 1/4] 读取数据文件...")
    input_path = settings.data.input_path
    df = read_excel(str(input_path))
    audit_logger.safe_log(
        "DATA_LOADED",
        f"从 {input_path.name} 读取 {len(df)} 条记录",
    )

    # --- 2b. 数据校验 ---
    logger.info("\n🔍 [阶段 2/4] 数据质量校验...")
    try:
        validate_columns(df)
    except DataException as e:
        logger.error(f"列校验失败: {e}")
        audit_logger.safe_log("VALIDATION_FAILED", str(e))
        return 1

    errors = validate_dataframe(df)
    if errors:
        logger.warning(f"发现 {len(errors)} 条数据质量问题:")
        for err in errors[:5]:  # 只显示前5条
            logger.warning(f"  ⚠ {err}")
        audit_logger.safe_log(
            "VALIDATION_WARNINGS",
            f"发现 {len(errors)} 条数据质量问题",
        )
    else:
        logger.info("✅ 数据质量校验通过")

    # --- 2c. 自动对账 ---
    logger.info("\n⚖️ [阶段 3/4] 执行自动对账...")
    result_df, summary = reconcile_dataframe(df)
    audit_logger.log(
        "RECONCILIATION_DONE",
        f"对账完成: {summary.total_records}条记录, "
        f"{summary.matched_records}条一致, "
        f"{summary.unmatched_records}条异常, "
        f"一致率{summary.match_rate}%",
    )

    # --- 2d. 生成报告 ---
    logger.info("\n📊 [阶段 4/4] 生成审计报告...")
    output_path = settings.data.output_path
    report_path = generate_report(result_df, summary, str(output_path))
    audit_logger.log(
        "REPORT_GENERATED",
        f"审计报告已保存: {report_path.name}",
    )

    # --- 输出摘要 ---
    logger.info("\n" + "=" * 60)
    logger.info("📋 审计结果摘要")
    logger.info("=" * 60)
    logger.info(f"  处理记录: {summary.total_records}")
    logger.info(f"  ✅ 一致: {summary.matched_records}")
    if summary.unmatched_records > 0:
        logger.info(f"  ❌ 异常: {summary.unmatched_records}")
    logger.info(f"  一致率: {summary.match_rate:.2f}%")
    logger.info(f"  总差异金额: ¥{summary.total_discrepancy:,.2f}")
    logger.info(f"  报告文件: {report_path}")
    logger.info("=" * 60)

    if summary.unmatched_records > 0:
        logger.warning(
            f"⚠️ 发现 {summary.unmatched_records} 条对账异常，"
            f"建议人工复核"
        )

    return 0 if summary.unmatched_records == 0 else 1


# =============================================================================
# 主入口
# =============================================================================

def main() -> None:
    """
    系统主入口

    执行流程：健康检查 -> 审计执行 -> 清理关闭 -> 退出
    """
    logger.info(f"{__app_name__} v{__version__} 启动")

    exit_code = 0

    try:
        if not check_environment():
            logger.info("\n💡 提示: 先运行模拟数据生成器...")
            logger.info("   python -m insurance_audit.data.generator")
            logger.info("   或:  insurance-audit --generate-mock")
            exit_code = 1
            return

        exit_code = run_audit()

    except DataException as e:
        logger.error(f"❌ 数据异常: {e}")
        audit_logger.safe_log("DATA_ERROR", str(e))
        exit_code = 1
    except SecurityException as e:
        logger.critical(f"🔒 安全异常: {e}")
        audit_logger.safe_log("SECURITY_ALERT", str(e))
        exit_code = 3
    except SystemException as e:
        logger.error(f"❌ 系统异常: {e}")
        audit_logger.safe_log("SYSTEM_ERROR", str(e))
        exit_code = 2
    except InsuranceAuditError as e:
        logger.error(f"❌ 审计异常 [{e.error_code}]: {e}")
        audit_logger.safe_log("UNKNOWN_ERROR", str(e))
        exit_code = 9
    except Exception as e:
        logger.critical(f"💥 未预期异常: {e}")
        audit_logger.safe_log("CRITICAL_ERROR", str(e))
        exit_code = 99
    finally:
        audit_logger.safe_log(
            "AUDIT_COMPLETE",
            f"审计流程结束，退出码={exit_code}",
        )
        logger.info(f"审计流程结束 (退出码: {exit_code})")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

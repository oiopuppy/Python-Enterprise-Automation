"""
保险理赔数据自动化审计工具 — 主入口

工作流：
1. 初始化日志
2. 健康检查（环境、文件就绪）
3. 执行审计引擎（读取 → 校验 → 对账 → 报告）
4. 审计追溯

退出码约定：
    0 = 审计完成且全部一致
    1 = 审计完成但存在对账异常 / 解析失败 / 数据文件缺失
    2 = 系统异常
    3 = 安全异常
    9 = 其他业务异常
   99 = 未预期异常
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from insurance_audit import __app_name__, __version__
from insurance_audit.audit.manifest import write_manifest
from insurance_audit.audit.reporter import build_json_payload, write_json_report
from insurance_audit.core.engine import AuditEngine
from insurance_audit.data.generator import generate_mock_data
from insurance_audit.models.claim import AuditSummary
from insurance_audit.utils.config import settings
from insurance_audit.utils.exceptions import (
    DataException,
    InsuranceAuditError,
    SecurityException,
    SystemException,
)
from insurance_audit.utils.logger import get_audit_logger, get_logger, setup_logging

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_AUDIT_ISSUE = 1
EXIT_SYSTEM_ERROR = 2
EXIT_SECURITY_ERROR = 3
EXIT_BUSINESS_ERROR = 9
EXIT_UNEXPECTED = 99


# =============================================================================
# 阶段 1：环境健康检查
# =============================================================================


def check_environment(input_path: Path) -> bool:
    """
    执行环境健康检查

    检查项：
    - 数据文件是否存在
    - 日志目录是否可写（由 setup_logging 保证）
    """
    logger.info("=" * 60)
    logger.info(f"--- {__app_name__} v{__version__} ---")
    logger.info(f"执行环境: {settings.app.env}")
    logger.info(f"数据文件: {input_path}")
    logger.info(f"输出目录: {settings.data.output_dir}")
    logger.info(f"审计模式: {'开启' if settings.app.is_production else '开发'}")
    logger.info("=" * 60)

    if not input_path.exists():
        logger.warning(
            f"数据文件不存在: {input_path}\n"
            f"  建议运行: insurance-audit --generate-mock 生成模拟数据"
        )
        return False

    logger.info(f"[OK] 数据文件就绪: {input_path.name}")
    return True


# =============================================================================
# 阶段 2：审计执行
# =============================================================================


def _write_json_stdout(payload: dict[str, Any]) -> None:
    """把 JSON 以 UTF-8 写到 stdout。

    Windows 控制台/管道的默认编码是 GBK，直接 ``print`` 会写出非 UTF-8 字节，
    下游 ``json.load`` 就会失败；这里直接写字节流，保证管道里也是 UTF-8。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # 测试框架可能把 stdout 换成了纯文本流
        print(text)
        return
    buffer.write((text + "\n").encode("utf-8"))
    buffer.flush()


FAIL_ON_CHOICES = ("any", "material", "parse-error", "none")


def resolve_exit_code(summary: AuditSummary, fail_on: str = "any") -> int:
    """按闸门策略把对账结果映射成业务退出码。

    - ``any``：有任何异常或解析失败即退出 1（v2.0.0 的默认行为）；
    - ``material``：只有重大差异才退出 1；
    - ``parse-error``：只有解析失败才退出 1；
    - ``none``：审计结果不影响退出码。
    """
    if fail_on == "none":
        return EXIT_OK
    if fail_on == "parse-error":
        blocked = summary.parse_error_records > 0
    elif fail_on == "material":
        blocked = summary.material_records > 0
    else:
        blocked = summary.unmatched_records > 0 or summary.parse_error_records > 0
    return EXIT_AUDIT_ISSUE if blocked else EXIT_OK


def run_audit(
    input_path: Path,
    output_path: Path,
    emit_json: bool = False,
    json_out: Optional[Path] = None,
    manifest_out: Optional[Path] = None,
    fail_on: str = "any",
) -> int:
    """
    执行完整的审计工作流

    具体的「读取 → 校验 → 对账 → 报告」由 AuditEngine 统一编排，
    这里只负责日志、审计追溯与退出码。

    Args:
        input_path: 待审计的 Excel 路径
        output_path: 审计报告输出路径
        emit_json: 是否把 JSON 摘要打印到 stdout（日志走 stderr，stdout 保持纯 JSON）
        json_out: 可选的 JSON 摘要落盘路径
        manifest_out: 可选的审计清单落盘路径（输入哈希/版本/配置）
        fail_on: 闸门策略（any/material/parse-error/none）

    Returns:
        0 = 未触发闸门；1 = 触发闸门（具体取决于 fail_on）
    """
    audit = get_audit_logger()
    audit.safe_log("AUDIT_START", "开始执行理赔数据审计流程")

    logger.info("\n[阶段 1/2] 执行审计引擎（读取 → 校验 → 对账 → 报告）...")
    engine = AuditEngine(input_file=str(input_path), output_file=str(output_path))
    summary = engine.run()

    if emit_json or json_out is not None:
        payload = build_json_payload(
            summary,
            input_file=str(input_path),
            output_file=str(output_path),
            validation_errors=engine.validation_errors,
        )
        if emit_json:
            # stdout 只输出 JSON（日志已走 stderr），可直接被 jq / json.load 消费
            _write_json_stdout(payload)
        if json_out is not None:
            write_json_report(payload, json_out)

    if manifest_out is not None and engine.manifest is not None:
        write_manifest(engine.manifest, manifest_out)

    audit.safe_log(
        "RECONCILIATION_DONE",
        f"对账完成: 读取{summary.source_records}条, "
        f"解析成功{summary.total_records}条, "
        f"解析失败{summary.parse_error_records}条, "
        f"{summary.matched_records}条一致, "
        f"{summary.unmatched_records}条异常, "
        f"一致率{summary.match_rate}%",
    )
    audit.safe_log("REPORT_GENERATED", f"审计报告已保存: {output_path.name}")

    # --- 输出摘要 ---
    logger.info("\n[阶段 2/2] 审计结果摘要")
    logger.info("=" * 60)
    logger.info(f"  读取记录: {summary.source_records}")
    logger.info(f"  成功解析: {summary.total_records}")
    if summary.parse_error_records > 0:
        logger.warning(f"  解析失败: {summary.parse_error_records}（已排除，详见报告）")
    logger.info(f"  [OK] 一致: {summary.matched_records}")
    if summary.unmatched_records > 0:
        logger.info(f"  [ERR] 异常: {summary.unmatched_records}")
    logger.info(f"  一致率: {summary.match_rate:.2f}%")
    logger.info(f"  总差异金额: {summary.total_discrepancy:,.2f} 元")
    logger.info(f"  报告文件: {output_path.absolute()}")
    logger.info("=" * 60)

    if summary.unmatched_records > 0:
        logger.warning(f"[WARN] 发现 {summary.unmatched_records} 条对账异常，建议人工复核")
        if summary.material_records > 0:
            logger.warning(f"[WARN] 其中 {summary.material_records} 条为重大差异")
    if summary.parse_error_records > 0:
        logger.warning(f"[WARN] 有 {summary.parse_error_records} 条记录无法解析，未计入一致率")

    return resolve_exit_code(summary, fail_on)


# =============================================================================
# 主入口
# =============================================================================


def main() -> None:
    """
    系统主入口

    支持CLI参数：
      insurance-audit                              # 使用配置中的默认路径执行审计
      insurance-audit --generate-mock              # 生成模拟数据后执行审计
      insurance-audit --input data.xlsx            # 指定输入文件
      insurance-audit --output report.xlsx         # 指定报告输出路径
    """
    parser = argparse.ArgumentParser(
        prog="insurance-audit",
        description=f"{__app_name__} v{__version__} — 保险理赔数据自动化审计系统",
    )
    parser.add_argument(
        "--generate-mock",
        action="store_true",
        help="首先生成模拟数据，再执行审计流程",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="待审计的 Excel 文件路径（默认使用配置中的 data/input 路径）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="审计报告输出路径（默认写入配置中的 reports/ 目录）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="把 JSON 摘要输出到 stdout（日志走 stderr，便于管道与调度）",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="同时把 JSON 摘要写入指定文件",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="额外输出一份 JSON 审计清单（输入 SHA256、工具版本与关键配置）",
    )
    parser.add_argument(
        "--fail-on",
        choices=FAIL_ON_CHOICES,
        default="any",
        help="闸门策略：any=有任何差异/解析失败即失败（默认），"
        "material=只有重大差异才失败，parse-error=只有解析失败才失败，none=不影响退出码",
    )
    args = parser.parse_args()

    # 日志配置必须在任何文件写入之前完成（库模块 import 时不建日志文件）
    setup_logging()

    input_path = Path(args.input) if args.input else settings.data.input_path
    output_path = Path(args.output) if args.output else settings.data.output_path
    json_out = Path(args.json_out) if args.json_out else None
    manifest_out = Path(args.manifest) if args.manifest else None

    logger.info(f"{__app_name__} v{__version__} 启动")

    exit_code = EXIT_OK
    audit = get_audit_logger()

    try:
        if args.generate_mock:
            logger.info("\n正在生成模拟理赔数据...")
            generate_mock_data(output_file=str(input_path))
            logger.info("")

        if not check_environment(input_path):
            logger.info("\n提示: 先运行模拟数据生成器...")
            logger.info("   insurance-audit --generate-mock")
            exit_code = EXIT_AUDIT_ISSUE
        else:
            exit_code = run_audit(
                input_path,
                output_path,
                args.json,
                json_out,
                manifest_out,
                args.fail_on,
            )

    except DataException as e:
        logger.error(f"[ERR] 数据异常: {e}")
        audit.safe_log("DATA_ERROR", str(e))
        exit_code = EXIT_AUDIT_ISSUE
    except SecurityException as e:
        logger.critical(f"[SEC] 安全异常: {e}")
        audit.safe_log("SECURITY_ALERT", str(e))
        exit_code = EXIT_SECURITY_ERROR
    except SystemException as e:
        logger.error(f"[ERR] 系统异常: {e}")
        audit.safe_log("SYSTEM_ERROR", str(e))
        exit_code = EXIT_SYSTEM_ERROR
    except InsuranceAuditError as e:
        logger.error(f"[ERR] 审计异常 [{e.error_code}]: {e}")
        audit.safe_log("UNKNOWN_ERROR", str(e))
        exit_code = EXIT_BUSINESS_ERROR
    except Exception as e:
        logger.critical(f"[CRIT] 未预期异常: {e}")
        audit.safe_log("CRITICAL_ERROR", str(e))
        exit_code = EXIT_UNEXPECTED
    finally:
        audit.safe_log("AUDIT_COMPLETE", f"审计流程结束，退出码={exit_code}")
        logger.info(f"审计流程结束 (退出码: {exit_code})")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

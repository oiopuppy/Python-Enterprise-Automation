"""
企业级日志系统 — Enterprise Logging System

设计要点：
1. 库模块只取 logger，**不在 import 时创建日志目录或文件** ——
   否则在只读环境、容器内无写权限目录、以及 ``--help`` 这类场景下会直接崩。
2. 真正的日志配置由 ``setup_logging()`` 显式完成，入口（main）负责调用。
3. 同时输出到控制台（彩色）和文件（轮转），审计日志单独落盘。
4. 控制台编码不保证能表示所有字符（中文 Windows 默认 GBK），
   这里用 ``errors="replace"`` 兜底，避免一条日志把整个进程打死。
"""

import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional, TextIO

from insurance_audit.utils.config import settings

# 颜色映射（仅控制台输出使用）
_COLORS = {
    "DEBUG": "\033[36m",  # Cyan
    "INFO": "\033[32m",  # Green
    "WARNING": "\033[33m",  # Yellow
    "ERROR": "\033[31m",  # Red
    "CRITICAL": "\033[41m",  # Red background
    "RESET": "\033[0m",
}


class ColorFormatter(logging.Formatter):
    """控制台彩色日志格式化器

    只在格式化期间临时改写 ``record.levelname``，结束后恢复原值：
    同一个 LogRecord 会被多个 handler 共享，直接改字段会把 ANSI 转义
    写进文件日志，也会污染其他 handler 的输出。
    """

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        color = _COLORS.get(original, _COLORS["RESET"])
        record.levelname = f"{color}{original:8s}{_COLORS['RESET']}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


class AuditLogger:
    """审计追溯专用日志器 — 记录所有操作变更"""

    _instance: Optional["AuditLogger"] = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls) -> "AuditLogger":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._logger is not None:
            return
        self._logger = logging.getLogger("audit_trail")
        self._logger.setLevel(logging.INFO)
        self._logger.handlers.clear()

        # 检查审计功能是否启用
        if not settings.log.audit_enabled:
            return

        # 只写入文件，不输出控制台
        audit_path = settings.log.audit_log_path
        try:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                filename=str(audit_path),
                maxBytes=settings.log.max_bytes,
                backupCount=settings.log.backup_count,
                encoding="utf-8",
            )
        except OSError as e:
            # 只读目录 / 权限不足：审计文件写不了，但审计流程本身必须继续
            self._logger.warning(f"审计日志文件不可写 {audit_path}: {e}")
            return

        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | AUDIT | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self._logger.addHandler(handler)

    def log(self, action: str, detail: str, user: str = "SYSTEM") -> None:
        """记录审计事件"""
        if self._logger is None:
            return
        self._logger.info(f"{user} | {action} | {detail}")

    def safe_log(self, action: str, detail: str, user: str = "SYSTEM") -> None:
        """安全记录审计事件，失败时不中断主流程"""
        try:
            self.log(action, detail, user)
        except Exception as e:  # 审计日志故障不能影响审计本身
            logging.getLogger(__name__).error(f"审计日志写入失败 [{action}]: {e}")


# 审计日志单例（惰性创建：第一次 get_audit_logger() 时才建文件）
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """获取审计日志单例（首次调用时才初始化文件 handler）"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# =============================================================================
# 日志管理器
# =============================================================================

_loggers: dict[str, logging.Logger] = {}
_root_configured = False


def get_logger(name: str) -> logging.Logger:
    """
    获取模块日志器

    注意：这里只返回 logger，不配置 handler。日志目录/文件由入口调用
    ``setup_logging()`` 时统一创建，库模块 import 不产生任何副作用。
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


def setup_logging() -> None:
    """配置根日志器（控制台 + 文件），重复调用只生效一次"""
    global _root_configured
    if _root_configured:
        return
    _configure_root_logger()
    _root_configured = True


def _console_stream() -> TextIO:
    """返回一个不会因编码问题抛异常的 stdout 包装"""
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")
    return stream


def _configure_root_logger() -> None:
    """配置根日志器 — 同时输出到控制台和文件"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log.level, logging.INFO))

    # 清空默认处理器
    root.handlers.clear()

    # --- 文件日志（带轮转）---
    log_path = settings.log.log_path
    file_ok = True
    log_error: Optional[OSError] = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=settings.log.max_bytes,
            backupCount=settings.log.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)
    except OSError as e:
        # 只读环境（容器挂载、无权限目录）：降级为仅控制台，不让日志拖垮业务
        file_ok = False
        log_error = e

    # --- 控制台日志（彩色）---
    console_handler = logging.StreamHandler(_console_stream())
    console_handler.setFormatter(
        ColorFormatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console_handler)

    if not file_ok:
        root.warning(f"日志文件不可写 {log_path}: {log_error}，已降级为仅控制台输出")

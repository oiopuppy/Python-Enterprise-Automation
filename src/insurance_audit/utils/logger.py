"""
企业级日志系统 — Enterprise Logging System

功能：
1. 同时输出到控制台（彩色）和日志文件
2. 按日志文件大小自动轮转，保留30天
3. 独立的审计追溯日志
4. 支持结构化日志记录

央企要求：
- 日志可追溯、可审计
- 日志文件有备份轮转策略
- 日志级别可配置
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from insurance_audit.utils.config import settings

# 颜色映射（控制台输出使用）
_COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[41m",  # Red background
    "RESET": "\033[0m",
}


class ColorFormatter(logging.Formatter):
    """控制台彩色日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        color = _COLORS.get(levelname, _COLORS["RESET"])
        reset = _COLORS["RESET"]
        record.levelname = f"{color}{levelname:8s}{reset}"
        return super().format(record)


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
        handler = RotatingFileHandler(
            filename=str(settings.log.audit_log_path),
            maxBytes=settings.log.max_bytes,
            backupCount=settings.log.backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | AUDIT | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self._logger.addHandler(handler)

    def log(self, action: str, detail: str, user: str = "SYSTEM") -> None:
        """记录审计事件"""
        self._logger.info(f"{user} | {action} | {detail}")

    def safe_log(self, action: str, detail: str, user: str = "SYSTEM") -> None:
        """安全记录审计事件，失败时不中断主流程"""
        try:
            self.log(action, detail, user)
        except Exception as e:
            logging.getLogger(__name__).error(
                f"审计日志写入失败 [{action}]: {e}"
            )


# =============================================================================
# 日志管理器
# =============================================================================

_loggers: dict[str, logging.Logger] = {}
_root_configured = False


def get_logger(name: str) -> logging.Logger:
    """
    获取或创建日志器
    
    每个模块有自己的日志器，继承根日志器的配置
    """
    global _root_configured
    
    if name in _loggers:
        return _loggers[name]

    if not _root_configured:
        _configure_root_logger()
        _root_configured = True

    logger = logging.getLogger(name)
    _loggers[name] = logger
    return logger


def _configure_root_logger() -> None:
    """配置根日志器 — 同时输出到控制台和文件"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log.level, logging.INFO))
    
    # 清空默认处理器
    root.handlers.clear()

    # --- 文件日志（带轮转）---
    log_path = settings.log.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=settings.log.max_bytes,
        backupCount=settings.log.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # --- 控制台日志（彩色）---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console_handler)


# 审计日志单例
audit_logger = AuditLogger()

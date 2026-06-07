"""
企业级配置管理 — Enterprise Configuration Management

支持多层级配置加载：
1. 默认配置（代码内硬编码兜底）
2. 环境变量（.env文件 / 系统环境变量）
3. 命令行参数（最高优先级）

央企要求：配置中心化、参数可配、环境隔离
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from insurance_audit.utils.exceptions import ConfigurationError


# =============================================================================
# 加载 .env 文件
# =============================================================================

# 尝试从项目根目录加载 .env
_project_root = Path(__file__).resolve().parents[3]
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)
else:
    # 尝试加载 .env.example（开发环境无 .env 时提供默认值）
    _example_env = _project_root / ".env.example"
    if _example_env.exists():
        load_dotenv(_example_env, override=False)


# =============================================================================
# 配置类
# =============================================================================


@dataclass(frozen=True)
class InsuranceConfig:
    """保险业务参数配置"""
    default_deductible: Decimal = field(
        default_factory=lambda: Decimal(
            os.getenv("INSURANCE_DEFAULT_DEDUCTIBLE", "500")
        )
    )
    default_ratio: Decimal = field(
        default_factory=lambda: Decimal(
            os.getenv("INSURANCE_DEFAULT_RATIO", "0.80")
        )
    )
    decimal_places: int = int(os.getenv("INSURANCE_DECIMAL_PLACES", "2"))
    annual_limit: Decimal = field(
        default_factory=lambda: Decimal(
            os.getenv("INSURANCE_ANNUAL_LIMIT", "500000")
        )
    )

    def __post_init__(self) -> None:
        """验证配置合法性"""
        if self.default_deductible < 0:
            raise ConfigurationError("免赔额不能为负数", "INSURANCE_DEFAULT_DEDUCTIBLE")
        if not Decimal("0") <= self.default_ratio <= Decimal("1"):
            raise ConfigurationError("赔付比例必须在0~1之间", "INSURANCE_DEFAULT_RATIO")
        if self.decimal_places < 0 or self.decimal_places > 10:
            raise ConfigurationError("小数位数必须在0~10之间", "INSURANCE_DECIMAL_PLACES")


@dataclass(frozen=True)
class DataConfig:
    """数据文件配置"""
    input_file: str = field(
        default_factory=lambda: os.getenv("DATA_INPUT_FILE", "sample_claim_data.xlsx")
    )
    output_file: str = field(
        default_factory=lambda: os.getenv("DATA_OUTPUT_FILE", "final_settlement_report.xlsx")
    )
    output_dir: str = field(
        default_factory=lambda: os.getenv("DATA_OUTPUT_DIR", "reports")
    )

    @property
    def output_path(self) -> Path:
        """获取输出文件的完整路径"""
        base = _project_root / self.output_dir
        base.mkdir(parents=True, exist_ok=True)
        return base / self.output_file

    @property
    def input_path(self) -> Path:
        """获取输入文件的完整路径"""
        path = Path(self.input_file)
        if not path.is_absolute():
            path = _project_root / path
        return path


@dataclass(frozen=True)
class LogConfig:
    """日志配置"""
    level: str = field(
        default_factory=lambda: os.getenv("APP_LOG_LEVEL", "INFO").upper()
    )
    log_file: str = field(
        default_factory=lambda: os.getenv("APP_LOG_FILE", "logs/audit.log")
    )
    max_bytes: int = int(os.getenv("APP_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    backup_count: int = int(os.getenv("APP_LOG_BACKUP_COUNT", "30"))
    audit_log_file: str = field(
        default_factory=lambda: os.getenv("AUDIT_LOG_FILE", "logs/audit_trail.log")
    )

    @property
    def log_path(self) -> Path:
        path = Path(self.log_file)
        if not path.is_absolute():
            path = _project_root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def audit_log_path(self) -> Path:
        path = Path(self.audit_log_file)
        if not path.is_absolute():
            path = _project_root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@dataclass(frozen=True)
class AppConfig:
    """应用主配置"""
    name: str = field(
        default_factory=lambda: os.getenv("APP_NAME", "保险理赔审计系统")
    )
    env: str = field(
        default_factory=lambda: os.getenv("APP_ENV", "development")
    )
    debug: bool = field(
        default_factory=lambda: os.getenv("APP_DEBUG", "true").lower() == "true"
    )

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"


# =============================================================================
# 全局配置单例
# =============================================================================


class Settings:
    """
    全局设置中心 — 单例模式
    
    使用方式：
        from insurance_audit.utils.config import settings
        settings.insurance.default_deductible
        settings.data.input_file
    """

    _instance: Optional["Settings"] = None

    def __new__(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.app = AppConfig()
        self.insurance = InsuranceConfig()
        self.data = DataConfig()
        self.log = LogConfig()
        self._initialized = True


# 全局单例
settings = Settings()

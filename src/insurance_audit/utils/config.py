"""
配置管理：三级加载，明确优先级

加载顺序：
1. 默认配置（代码内兜底）
2. 环境变量（.env 文件 / 系统环境变量）
3. 命令行参数（最高优先级）
"""

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Union

from dotenv import load_dotenv

from insurance_audit.utils.exceptions import ConfigurationError

# =============================================================================
# 加载 .env 文件
# =============================================================================

# 项目根目录：优先取 PROJECT_ROOT（容器/自定义部署），否则按源码位置推断。
# 容器里源码被装进 site-packages，靠 parents[3] 会指到 Python 安装目录，
# 因此 Dockerfile 里显式设置 PROJECT_ROOT=/app。
_default_project_root = Path(__file__).resolve().parents[3]
_project_root = Path(os.getenv("PROJECT_ROOT", str(_default_project_root))).resolve()
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
        default_factory=lambda: Decimal(os.getenv("INSURANCE_DEFAULT_DEDUCTIBLE", "500"))
    )
    default_ratio: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_DEFAULT_RATIO", "0.80"))
    )
    decimal_places: int = int(os.getenv("INSURANCE_DECIMAL_PLACES", "2"))
    annual_limit: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_ANNUAL_LIMIT", "500000"))
    )
    policy_prefix: str = field(default_factory=lambda: os.getenv("INSURANCE_POLICY_PREFIX", "CL"))
    min_claim_amount: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_MIN_CLAIM_AMOUNT", "0.01"))
    )
    max_claim_amount: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_MAX_CLAIM_AMOUNT", "99999999.99"))
    )
    tolerance_absolute: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_TOLERANCE_ABSOLUTE", "0.01"))
    )
    tolerance_ratio: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_TOLERANCE_RATIO", "0.001"))
    )
    minor_threshold: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_MINOR_THRESHOLD", "1.00"))
    )
    material_threshold: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("INSURANCE_MATERIAL_THRESHOLD", "100.00"))
    )

    def __post_init__(self) -> None:
        """验证配置合法性"""
        if self.default_deductible < 0:
            raise ConfigurationError("免赔额不能为负数", "INSURANCE_DEFAULT_DEDUCTIBLE")
        if not Decimal("0") <= self.default_ratio <= Decimal("1"):
            raise ConfigurationError("赔付比例必须在0~1之间", "INSURANCE_DEFAULT_RATIO")
        if self.decimal_places < 0 or self.decimal_places > 10:
            raise ConfigurationError("小数位数必须在0~10之间", "INSURANCE_DECIMAL_PLACES")
        if not self.policy_prefix or not self.policy_prefix.strip():
            raise ConfigurationError("保单前缀不能为空或仅空格", "INSURANCE_POLICY_PREFIX")
        if self.min_claim_amount <= Decimal("0"):
            raise ConfigurationError("最小报案金额必须大于0", "INSURANCE_MIN_CLAIM_AMOUNT")
        if self.max_claim_amount <= self.min_claim_amount:
            raise ConfigurationError(
                "最大报案金额必须大于最小报案金额",
                "INSURANCE_MAX_CLAIM_AMOUNT",
            )
        if self.tolerance_absolute < 0:
            raise ConfigurationError("绝对容差不能为负数", "INSURANCE_TOLERANCE_ABSOLUTE")
        if not Decimal("0") <= self.tolerance_ratio <= Decimal("1"):
            raise ConfigurationError("相对容差比例必须在0~1之间", "INSURANCE_TOLERANCE_RATIO")
        if self.minor_threshold <= 0:
            raise ConfigurationError("轻微差异阈值必须大于0", "INSURANCE_MINOR_THRESHOLD")
        if self.material_threshold <= self.minor_threshold:
            raise ConfigurationError(
                "重大差异阈值必须大于轻微差异阈值",
                "INSURANCE_MATERIAL_THRESHOLD",
            )


# =============================================================================
# 映射 profile：标准字段与取值域
# =============================================================================

# 标准字段：数据模型 v2 的字段名。前 6 个是 v2.0.0 既有的核心字段，
# 后面的属于 v2 扩展，全部可选，老台账不填不影响。
STANDARD_FIELDS: tuple[str, ...] = (
    "保单号",
    "客户姓名",
    "报案金额",
    "免赔额",
    "赔付比例",
    "实际赔付金额",
    "赔案号",
    "被保险人",
    "保额",
    "案件状态",
    "收款账号哈希",
    "报案日期",
    "受理日期",
    "核定日期",
    "支付日期",
)

# 文件角色：一个客户通常有一份台账，还没到多源对账（#32）的阶段
PROFILE_ROLES: tuple[str, ...] = ("ledger", "payment", "core")

# 金额单位：真实台账常以「万元」录入
AMOUNT_UNITS: tuple[str, ...] = ("yuan", "wan")


@dataclass(frozen=True)
class MappingProfile:
    """客户台账的列映射 profile

    客户原始表的列名千差万别（赔案号 / 出险金额 / 核赔金额……），
    这里把「标准字段 → 源列名」的对应关系、主键、时间轴、日期格式、
    金额单位、读取参数集中描述，读取层按 profile 把源表整形成标准列，
    下游的校验、对账、报告都不需要知道客户原来怎么写的。

    字段说明：
        role: 文件角色，ledger（台账）/ payment（支付流水）/ core（核心系统）
        columns: 标准字段 -> 源列名；不在其中的标准字段按同名匹配
        primary_key: 主键组合（标准字段名）
        timeline: 时间轴字段（标准字段名，按业务先后排序）
        date_formats: 日期解析格式，按顺序尝试
        amount_unit: 金额单位，yuan（元）/ wan（万元）
        tolerance_absolute / tolerance_ratio: 覆盖全局容差（不填用全局配置）
        sheet: Excel 的 sheet 名（留空取第一个）
        encoding: CSV 编码（留空自动探测）
        skiprows: 表头之前要跳过的说明行数
    """

    role: str = "ledger"
    columns: dict[str, str] = field(default_factory=dict)
    primary_key: tuple[str, ...] = ("保单号",)
    timeline: tuple[str, ...] = ()
    date_formats: tuple[str, ...] = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y年%m月%d日")
    amount_unit: str = "yuan"
    tolerance_absolute: Optional[Decimal] = None
    tolerance_ratio: Optional[Decimal] = None
    sheet: Optional[str] = None
    encoding: Optional[str] = None
    skiprows: int = 0

    def __post_init__(self) -> None:
        if self.role not in PROFILE_ROLES:
            raise ConfigurationError(
                f"profile 的 role 必须是 {list(PROFILE_ROLES)} 之一: {self.role!r}", "role"
            )
        if self.amount_unit not in AMOUNT_UNITS:
            raise ConfigurationError(
                f"profile 的 amount_unit 必须是 {list(AMOUNT_UNITS)} 之一: {self.amount_unit!r}",
                "amount_unit",
            )
        unknown = [name for name in self.columns if name not in STANDARD_FIELDS]
        if unknown:
            raise ConfigurationError(
                f"profile 的 columns 里有未知标准字段: {unknown}；"
                f"可用标准字段: {list(STANDARD_FIELDS)}",
                "columns",
            )
        unknown_keys = [name for name in self.primary_key if name not in STANDARD_FIELDS]
        if unknown_keys:
            raise ConfigurationError(
                f"profile 的 primary_key 里有未知标准字段: {unknown_keys}", "primary_key"
            )
        unknown_timeline = [name for name in self.timeline if name not in STANDARD_FIELDS]
        if unknown_timeline:
            raise ConfigurationError(
                f"profile 的 timeline 里有未知标准字段: {unknown_timeline}", "timeline"
            )
        if self.skiprows < 0:
            raise ConfigurationError("profile 的 skiprows 不能为负数", "skiprows")
        if self.tolerance_absolute is not None and self.tolerance_absolute < 0:
            raise ConfigurationError(
                "profile 的 tolerance_absolute 不能为负数", "tolerance_absolute"
            )
        if self.tolerance_ratio is not None and not Decimal("0") <= self.tolerance_ratio <= Decimal(
            "1"
        ):
            raise ConfigurationError(
                "profile 的 tolerance_ratio 必须在 0~1 之间", "tolerance_ratio"
            )

    @property
    def column_map(self) -> dict[str, str]:
        """源列名 -> 标准字段（读取层做 rename 用的方向）"""
        return {source: standard for standard, source in self.columns.items()}


def _profile_from_mapping(data: dict[str, Any], source: str) -> MappingProfile:
    """把 profile 文件的字典解析成 MappingProfile，并给出定位到源的报错"""
    if not isinstance(data, dict):
        raise ConfigurationError(f"profile 内容必须是 JSON 对象: {source}", "profile")

    columns_raw = data.get("columns") or {}
    if not isinstance(columns_raw, dict):
        raise ConfigurationError(
            f"profile 的 columns 必须是对象（标准字段 -> 源列名）: {source}", "columns"
        )

    def _as_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            return tuple(str(item) for item in value)
        raise ConfigurationError(
            f"profile 的字段应为字符串或数组: {value!r}（{source}）", "profile"
        )

    def _as_decimal(value: Any, key: str) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as e:
            raise ConfigurationError(
                f"profile 的 {key} 不是合法数字: {value!r}（{source}）", key
            ) from e

    try:
        return MappingProfile(
            role=str(data.get("role", "ledger")),
            columns={str(k): str(v) for k, v in columns_raw.items()},
            primary_key=_as_tuple(data.get("primary_key")) or ("保单号",),
            timeline=_as_tuple(data.get("timeline")),
            date_formats=_as_tuple(data.get("date_formats"))
            or ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y年%m月%d日"),
            amount_unit=str(data.get("amount_unit", "yuan")),
            tolerance_absolute=_as_decimal(data.get("tolerance_absolute"), "tolerance_absolute"),
            tolerance_ratio=_as_decimal(data.get("tolerance_ratio"), "tolerance_ratio"),
            sheet=data.get("sheet") or None,
            encoding=data.get("encoding") or None,
            skiprows=int(data.get("skiprows", 0)),
        )
    except ConfigurationError as e:
        raise ConfigurationError(f"{e}；来源: {source}", "profile") from e
    except (TypeError, ValueError) as e:
        raise ConfigurationError(f"profile 格式不正确（{source}）: {e}", "profile") from e


def load_profile(source: Union[str, Path, MappingProfile, None] = None) -> MappingProfile:
    """加载映射 profile

    Args:
        source: MappingProfile 实例、profile 文件路径（JSON）或 None

    Returns:
        MappingProfile；None 时返回内置默认（标准 6 列、元为单位、第一个 sheet）

    Raises:
        ConfigurationError: profile 文件不存在、不是合法 JSON 或字段非法

    未显式传入时会读取环境变量 ``DATA_PROFILE``，便于按客户切换而不用改命令行。
    """
    if isinstance(source, MappingProfile):
        return source
    if source is None:
        source = os.getenv("DATA_PROFILE") or None
        if not source:
            return MappingProfile()
    path = Path(source)
    if not path.is_absolute():
        path = _project_root / path
    if not path.exists():
        raise ConfigurationError(f"profile 文件不存在: {path}", "DATA_PROFILE")
    try:
        # utf-8-sig：Windows 记事本/Excel 另存的 JSON 常带 BOM，带 BOM 也能读
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ConfigurationError(
            f"profile 不是 UTF-8 编码: {path}（请另存为 UTF-8）", "DATA_PROFILE"
        ) from e
    except OSError as e:
        raise ConfigurationError(f"profile 文件读取失败: {path}（{e}）", "DATA_PROFILE") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"profile 不是合法 JSON: {path} 第 {e.lineno} 行第 {e.colno} 列: {e.msg}",
            "DATA_PROFILE",
        ) from e
    return _profile_from_mapping(data, str(path))


@dataclass(frozen=True)
class DataConfig:
    """数据文件配置"""

    input_file: str = field(
        default_factory=lambda: os.getenv("DATA_INPUT_FILE", "sample_claim_data.xlsx")
    )
    output_file: str = field(
        default_factory=lambda: os.getenv("DATA_OUTPUT_FILE", "final_settlement_report.xlsx")
    )
    output_dir: str = field(default_factory=lambda: os.getenv("DATA_OUTPUT_DIR", "reports"))
    profile_file: str = field(default_factory=lambda: os.getenv("DATA_PROFILE", ""))

    @property
    def profile(self) -> MappingProfile:
        """当前配置的映射 profile（未指定则为内置默认）"""
        return load_profile(self.profile_file or None)

    @property
    def output_path(self) -> Path:
        """
        获取输出文件的完整路径

        这里不创建目录：路径解析应在只读环境（如 --help、环境检查）下也安全，
        目录创建交给真正写文件的 I/O 层。
        """
        base = _project_root / self.output_dir
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

    level: str = field(default_factory=lambda: os.getenv("APP_LOG_LEVEL", "INFO").upper())
    log_file: str = field(default_factory=lambda: os.getenv("APP_LOG_FILE", "logs/audit.log"))
    max_bytes: int = int(os.getenv("APP_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    backup_count: int = int(os.getenv("APP_LOG_BACKUP_COUNT", "30"))
    audit_log_file: str = field(
        default_factory=lambda: os.getenv("AUDIT_LOG_FILE", "logs/audit_trail.log")
    )
    audit_enabled: bool = field(
        default_factory=lambda: os.getenv("AUDIT_ENABLED", "true").lower() == "true"
    )

    @property
    def log_path(self) -> Path:
        path = Path(self.log_file)
        if not path.is_absolute():
            path = _project_root / path
        return path

    @property
    def audit_log_path(self) -> Path:
        path = Path(self.audit_log_file)
        if not path.is_absolute():
            path = _project_root / path
        return path


@dataclass(frozen=True)
class AppConfig:
    """应用主配置"""

    name: str = field(default_factory=lambda: os.getenv("APP_NAME", "保险理赔审计系统"))
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    debug: bool = field(default_factory=lambda: os.getenv("APP_DEBUG", "true").lower() == "true")

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

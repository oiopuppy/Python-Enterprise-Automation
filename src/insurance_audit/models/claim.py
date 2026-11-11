"""
理赔数据模型 — Claim Data Models

使用 Pydantic v2 提供：
- 强类型校验
- 自动类型转换
- 序列化/反序列化
- 业务规则验证
"""

from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from insurance_audit.utils.config import settings

# 差异级别：审计状态仍只有「一致 / 异常」，级别用于说明异常有多严重
DIFF_LEVEL_MATCH = "一致"
DIFF_LEVEL_MINOR = "轻微"
DIFF_LEVEL_NORMAL = "一般"
DIFF_LEVEL_MATERIAL = "重大"

# 容差默认值：绝对金额与相对比例取较大者，避免大额保单被 1 分钱卡住
DEFAULT_TOLERANCE_ABSOLUTE = Decimal("0.01")
DEFAULT_TOLERANCE_RATIO = Decimal("0.001")


def tolerance_for(claim_amount: Decimal, absolute: Optional[Decimal] = None) -> Decimal:
    """单条记录的容差：``max(绝对容差, 报案金额 × 相对容差)``。"""
    abs_tol = settings.insurance.tolerance_absolute if absolute is None else absolute
    relative = claim_amount * settings.insurance.tolerance_ratio
    return max(abs_tol, relative)


def classify_difference(diff: Decimal, tolerance: Decimal) -> str:
    """把差异金额归到四个级别之一。

    - ``一致``：差异小于容差（与 v2.0.0 的 ``diff < tolerance`` 保持一致）；
    - ``轻微``：超过容差但不超过轻微阈值（默认 1 元）；
    - ``一般``：超过轻微阈值但小于重大阈值；
    - ``重大``：达到或超过重大阈值（默认 100 元）。
    """
    if diff < tolerance:
        return DIFF_LEVEL_MATCH
    if diff >= settings.insurance.material_threshold:
        return DIFF_LEVEL_MATERIAL
    if diff > settings.insurance.minor_threshold:
        return DIFF_LEVEL_NORMAL
    return DIFF_LEVEL_MINOR


class ClaimRecord(BaseModel):
    """单条理赔记录模型"""

    # Excel列名映射（中英文）
    policy_id: str = Field(
        ...,
        alias="保单号",
        description="保单编号，格式：CL9900XXX",
    )
    customer_name: str = Field(
        ...,
        alias="客户姓名",
        max_length=50,
    )
    claim_amount: Decimal = Field(
        ...,
        alias="报案金额",
        gt=Decimal("0"),
        description="报案金额（元），必须大于0",
    )
    deductible: Decimal = Field(
        ...,
        alias="免赔额",
        ge=Decimal("0"),
        description="免赔额（元），不能为负数",
    )
    payout_ratio: Decimal = Field(
        ...,
        alias="赔付比例",
        ge=Decimal("0"),
        le=Decimal("1"),
        description="赔付比例，0~1之间",
    )
    actual_payout: Decimal = Field(
        ...,
        alias="实际赔付金额",
        ge=Decimal("0"),
        description="原始表中的实际赔付金额",
    )

    # 系统计算字段（非Excel直接映射）
    calculated_payout: Optional[Decimal] = Field(
        default=None,
        description="系统核算的赔付金额",
    )
    audit_status: Optional[str] = Field(
        default=None,
        description="审计状态：一致/异常",
    )
    diff_level: Optional[str] = Field(
        default=None,
        description="差异级别：一致/轻微/一般/重大",
    )

    @field_validator("claim_amount", "deductible", mode="before")
    @classmethod
    def validate_amount_precision(cls, value: object) -> object:
        """确保金额精度不超过2位小数"""
        if isinstance(value, (int, float, str)):
            d = Decimal(str(value))
            exponent = d.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -2:
                raise ValueError(f"金额精度超过2位小数: {value}")
        return value

    @field_validator("policy_id", mode="before")
    @classmethod
    def validate_policy_id(cls, value: object) -> object:
        """根据配置中的前缀验证保单号格式"""
        raw = str(value).strip()
        prefix = settings.insurance.policy_prefix
        if not raw.startswith(prefix):
            raise ValueError(f"保单号必须以 '{prefix}' 开头: {raw}")
        suffix = raw[len(prefix) :]
        if not suffix or not suffix.isdigit():
            raise ValueError(f"保单号前缀后的部分必须全是数字: {raw}")
        return raw

    def calculate_payout(self) -> Decimal:
        """
        核心赔付计算逻辑

        公式：应赔额 = (报案金额 - 免赔额) * 赔付比例

        统一委托给 ``core.calculator.calculate_payout``，
        避免模型层与核心层各有一套公式、改一处漏一处。

        这里用函数内导入：calculator 需要 ClaimRecord 做类型标注，
        顶层导入会形成 claim -> calculator -> claim 的循环。
        """
        from insurance_audit.core.calculator import calculate_payout

        return calculate_payout(
            claim_amount=self.claim_amount,
            deductible=self.deductible,
            ratio=self.payout_ratio,
            policy_id=self.policy_id,
        )

    def reconcile(self, tolerance: Optional[Decimal] = None) -> tuple[bool, Decimal]:
        """
        对账比较：系统核算 vs 原始赔付

        Args:
            tolerance: 可选的自定义容差；默认按
                ``max(绝对容差, 报案金额 × 相对容差)`` 计算

        Returns:
            (是否一致, 差异金额)
        """
        calculated = self.calculate_payout()
        diff = abs(calculated - self.actual_payout)
        effective_tolerance = tolerance_for(self.claim_amount, tolerance)
        is_match = diff < effective_tolerance
        self.calculated_payout = calculated
        self.audit_status = "一致" if is_match else "异常"
        self.diff_level = classify_difference(diff, effective_tolerance)
        return is_match, diff

    model_config = ConfigDict(populate_by_name=True)


class AuditSummary(BaseModel):
    """审计结果摘要"""

    source_records: int = Field(default=0, description="从 Excel 读取到的总行数")
    total_records: int = Field(default=0, description="成功解析并参与对账的记录数")
    parse_error_records: int = Field(default=0, description="无法解析、被排除的对账记录数")
    parse_errors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="无法解析记录的明细（行号、保单号、原因）",
    )
    matched_records: int = 0
    unmatched_records: int = 0
    minor_records: int = Field(default=0, description="轻微差异记录数")
    normal_records: int = Field(default=0, description="一般差异记录数")
    material_records: int = Field(default=0, description="重大差异记录数")
    match_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    total_claim_amount: Decimal = Decimal("0.00")
    total_actual_payout: Decimal = Decimal("0.00")
    total_calculated_payout: Decimal = Decimal("0.00")
    total_discrepancy: Decimal = Decimal("0.00")
    execution_time: str = ""
    duplicate_policy_groups: int = Field(default=0, description="重复保单号组数")
    details: list[dict[str, Any]] = Field(default_factory=list)

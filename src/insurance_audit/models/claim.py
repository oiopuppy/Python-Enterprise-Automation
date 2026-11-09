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

    def reconcile(self) -> tuple[bool, Decimal]:
        """
        对账比较：系统核算 vs 原始赔付

        Returns:
            (是否一致, 差异金额)
        """
        calculated = self.calculate_payout()
        diff = abs(calculated - self.actual_payout)
        tolerance = Decimal(10) ** -settings.insurance.decimal_places
        is_match = diff < tolerance
        self.calculated_payout = calculated
        self.audit_status = "一致" if is_match else "异常"
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
    match_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    total_claim_amount: Decimal = Decimal("0.00")
    total_actual_payout: Decimal = Decimal("0.00")
    total_calculated_payout: Decimal = Decimal("0.00")
    total_discrepancy: Decimal = Decimal("0.00")
    execution_time: str = ""
    details: list[dict[str, Any]] = Field(default_factory=list)

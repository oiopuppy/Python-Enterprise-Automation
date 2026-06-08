"""
理赔数据模型 — Claim Data Models

使用 Pydantic v2 提供：
- 强类型校验
- 自动类型转换
- 序列化/反序列化
- 业务规则验证
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from insurance_audit.utils.config import settings


class ClaimRecord(BaseModel):
    """单条理赔记录模型"""

    # Excel列名映射（中英文）
    policy_id: str = Field(
        ..., alias="保单号",
        description="保单编号，格式：CL9900XXX",
        pattern=r"^CL\d{7}$",
    )
    customer_name: str = Field(
        ..., alias="客户姓名", max_length=50,
    )
    claim_amount: Decimal = Field(
        ..., alias="报案金额",
        gt=Decimal("0"),
        description="报案金额（元），必须大于0",
    )
    deductible: Decimal = Field(
        ..., alias="免赔额",
        ge=Decimal("0"),
        description="免赔额（元），不能为负数",
    )
    payout_ratio: Decimal = Field(
        ..., alias="赔付比例",
        ge=Decimal("0"),
        le=Decimal("1"),
        description="赔付比例，0~1之间",
    )
    actual_payout: Decimal = Field(
        ..., alias="实际赔付金额",
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
            if d.as_tuple().exponent < -2:
                raise ValueError(f"金额精度超过2位小数: {value}")
        return value

    @model_validator(mode="after")
    def validate_business_rules(self) -> "ClaimRecord":
        """跨字段业务规则验证"""
        if self.claim_amount <= self.deductible:
            # 低于免赔额时，赔付金额应为0
            pass  # 业务逻辑上允许，不算模型错误
        return self

    def calculate_payout(self) -> Decimal:
        """
        核心赔付计算逻辑
        公式：应赔额 = (报案金额 - 免赔额) * 赔付比例
        """
        if self.claim_amount <= self.deductible:
            return Decimal("0.00")

        payout = (self.claim_amount - self.deductible) * self.payout_ratio
        # 使用ROUND_HALF_UP四舍五入到2位小数（符合中国财务规范）
        return payout.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")

    def reconcile(self) -> tuple[bool, Decimal]:
        """
        对账比较：系统核算 vs 原始赔付
        
        Returns:
            (是否一致, 差异金额)
        """
        calculated = self.calculate_payout()
        diff = abs(calculated - self.actual_payout)
        tolerance = Decimal(10) ** (-settings.insurance.decimal_places - 1)
        is_match = diff < tolerance
        self.calculated_payout = calculated
        self.audit_status = "一致" if is_match else "异常"
        return is_match, diff


    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={Decimal: str},
    )


class AuditSummary(BaseModel):
    """审计结果摘要"""
    total_records: int = 0
    matched_records: int = 0
    unmatched_records: int = 0
    match_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    total_claim_amount: Decimal = Decimal("0.00")
    total_actual_payout: Decimal = Decimal("0.00")
    total_calculated_payout: Decimal = Decimal("0.00")
    total_discrepancy: Decimal = Decimal("0.00")
    execution_time: str = ""
    details: list[dict] = Field(default_factory=list)

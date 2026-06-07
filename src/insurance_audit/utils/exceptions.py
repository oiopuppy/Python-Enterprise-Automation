"""
企业级异常体系 — Enterprise Exception Hierarchy

央企生产环境要求异常分类明确：
- 业务异常（BusinessException）：业务规则违反，需人工介入
- 系统异常（SystemException）：基础设施故障，可重试
- 数据异常（DataException）：数据质量问题，需数据治理
- 安全异常（SecurityException）：安全违规，需审计
"""

from typing import Any, Optional


class InsuranceAuditError(Exception):
    """审计系统基础异常 — 所有异常的基类"""

    def __init__(
        self,
        message: str,
        error_code: str = "ERR-0000",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.error_code = error_code
        self.details = details or {}
        super().__init__(f"[{error_code}] {message}")


# =============================================================================
# 业务异常 — 业务规则被违反
# =============================================================================


class BusinessException(InsuranceAuditError):
    """业务规则异常——需要人工介入处理的业务逻辑问题"""

    def __init__(
        self,
        message: str,
        error_code: str = "BIZ-0001",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)


class ClaimAmountExceedsLimitError(BusinessException):
    """理赔金额超过年度上限"""

    def __init__(
        self,
        amount: float,
        limit: float,
        policy_id: str = "",
    ) -> None:
        super().__init__(
            message=f"理赔金额 {amount} 元超过年度赔付上限 {limit} 元 "
            f"(保单: {policy_id})",
            error_code="BIZ-0101",
            details={
                "amount": amount,
                "limit": limit,
                "policy_id": policy_id,
            },
        )


class NegativeClaimAmountError(BusinessException):
    """理赔金额为负数"""

    def __init__(self, amount: float) -> None:
        super().__init__(
            message=f"报案金额不能为负数: {amount}",
            error_code="BIZ-0102",
            details={"amount": amount},
        )


class InvalidDeductibleError(BusinessException):
    """免赔额不合法"""

    def __init__(self, deductible: float) -> None:
        super().__init__(
            message=f"免赔额不能为负数: {deductible}",
            error_code="BIZ-0103",
            details={"deductible": deductible},
        )


class InvalidRatioError(BusinessException):
    """赔付比例不合法"""

    def __init__(self, ratio: float) -> None:
        super().__init__(
            message=f"赔付比例必须在 0~1 之间: {ratio}",
            error_code="BIZ-0104",
            details={"ratio": ratio},
        )


class ReconciliationMismatchError(BusinessException):
    """对账差异——系统核算与原始数据不一致"""

    def __init__(
        self,
        policy_id: str,
        expected: float,
        actual: float,
    ) -> None:
        diff = abs(expected - actual)
        super().__init__(
            message=f"对账差异 — 保单 {policy_id}: "
            f"系统核算={expected}元, 原始={actual}元, 差异={diff}元",
            error_code="BIZ-0201",
            details={
                "policy_id": policy_id,
                "expected": expected,
                "actual": actual,
                "difference": round(diff, 2),
            },
        )


# =============================================================================
# 数据异常 — 数据质量问题
# =============================================================================


class DataException(InsuranceAuditError):
    """数据异常——数据读取/验证失败"""

    def __init__(
        self,
        message: str,
        error_code: str = "DAT-0001",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)


class FileNotFoundError(DataException):
    """数据文件不存在"""

    def __init__(self, file_path: str) -> None:
        super().__init__(
            message=f"数据文件不存在: {file_path}",
            error_code="DAT-0101",
            details={"file_path": file_path},
        )


class InvalidColumnError(DataException):
    """Excel列名缺失"""

    def __init__(self, missing_columns: list[str]) -> None:
        super().__init__(
            message=f"数据文件缺少必要列: {missing_columns}",
            error_code="DAT-0102",
            details={"missing_columns": missing_columns},
        )


class DataValidationError(DataException):
    """数据内容不合法"""

    def __init__(
        self,
        row_index: int,
        field: str,
        value: Any,
        reason: str,
    ) -> None:
        super().__init__(
            message=f"第 {row_index} 行数据校验失败: "
            f"[{field}] = {value}, 原因: {reason}",
            error_code="DAT-0201",
            details={
                "row_index": row_index,
                "field": field,
                "value": str(value),
                "reason": reason,
            },
        )


# =============================================================================
# 系统异常 — 基础设施问题
# =============================================================================


class SystemException(InsuranceAuditError):
    """系统异常——基础设施故障"""

    def __init__(
        self,
        message: str,
        error_code: str = "SYS-0001",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)


class IOFailure(SystemException):
    """IO操作失败"""

    def __init__(
        self,
        operation: str,
        path: str,
        original_error: str,
    ) -> None:
        super().__init__(
            message=f"IO操作失败 [{operation}]: {path} — {original_error}",
            error_code="SYS-0101",
            details={
                "operation": operation,
                "path": path,
                "original_error": original_error,
            },
        )


class ConfigurationError(SystemException):
    """配置错误"""

    def __init__(self, message: str, key: str = "") -> None:
        super().__init__(
            message=f"配置错误: {message} (key={key})",
            error_code="SYS-0201",
            details={"key": key},
        )


# =============================================================================
# 安全异常
# =============================================================================


class SecurityException(InsuranceAuditError):
    """安全异常——需记录审计日志"""

    def __init__(
        self,
        message: str,
        error_code: str = "SEC-0001",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)

"""
多源对账引擎 — 台账 ↔ 支付流水（Cross-source Reconciliation）

单表复核（``audit/reconciler.py``）回答的是「自己算的应赔额和表里填的实际赔付
对不对」；本模块回答财务月底更基础的问题：**台账记的每一笔，钱到底付出去没有**。

对账口径
--------
按主键（默认 ``保单号 + 赔案号``，可配）把两张表各自合并成「一个键一组」，
再比较两侧金额：

- ``matched``：两侧都有，金额差在容差内
- ``amount_diff``：两侧都有，金额差超出容差
- ``ledger_only``：台账有、流水没有（只记未付）
- ``payment_only``：流水有、台账没有（可能是账外赔付）
- ``status_diff``：金额对得上，但台账已结案而流水失败/退票（issue #32 的状态差）

恒等式
------
对账结果必须满足::

    Σ台账金额 == Σ流水金额 + Σ差异金额

差异金额带符号（台账 − 流水）。只统计「主键与金额都有效」的行：主键为空或金额
不可用的行不参与匹配与合计，而是逐条记进 ``issues`` 并计数。``identity_holds``
会复核一次上面的等式，不成立时记 error 日志并把标志置为 ``False``。

金额一律用 ``Decimal`` 计算，输出 DataFrame 里的金额列也是 ``Decimal``
（object dtype），所以调用方可以直接用 ``Decimal`` 复核合计，不会出现
``0.1 + 0.2 != 0.3`` 的浮点误差。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd
from pydantic import BaseModel, Field

from insurance_audit.models.claim import tolerance_for
from insurance_audit.utils.config import MappingProfile, load_profile, settings
from insurance_audit.utils.exceptions import InvalidColumnError
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# =============================================================================
# 对账结果（写进报告的「对账结果」列，英文标识与 issue 约定一致）
# =============================================================================
RESULT_MATCHED = "matched"
RESULT_AMOUNT_DIFF = "amount_diff"
RESULT_LEDGER_ONLY = "ledger_only"
RESULT_PAYMENT_ONLY = "payment_only"
RESULT_STATUS_DIFF = "status_diff"

# 匹配类型：描述一个键两侧各有多少笔
MATCH_ONE_TO_ONE = "一对一"
MATCH_ONE_TO_MANY = "一对多"
MATCH_MANY_TO_ONE = "多对一"
MATCH_MANY_TO_MANY = "多对多"
MATCH_LEDGER_ONLY = "台账单边"
MATCH_PAYMENT_ONLY = "流水单边"

# 脏数据的分类（写进 issues[].reason）
ISSUE_EMPTY_KEY = "主键为空"
ISSUE_INVALID_AMOUNT = "金额不可用"
ISSUE_DUPLICATE_KEY = "重复主键"

# 默认口径
DEFAULT_KEY_FIELDS: tuple[str, ...] = ("保单号", "赔案号")
DEFAULT_AMOUNT_FIELD = "实际赔付金额"
DEFAULT_STATUS_FIELD = "案件状态"

# 状态一致性：两侧对「钱到底付出去没有」的判断相反
# 台账侧「已结案」的写法 → 台账说钱该付/已付
LEDGER_CLOSED_STATES: tuple[str, ...] = ("已结案", "结案", "已赔付", "赔付完成", "已完成")
# 流水侧「已付成功」的写法
PAYMENT_CLOSED_STATES: tuple[str, ...] = (
    "成功",
    "已成功",
    "已支付",
    "支付成功",
    "已赔付",
    "完成",
    "已完成",
)
# 台账侧的退票/失败（台账挂着「钱退回来了」）
LEDGER_FAILED_STATES: tuple[str, ...] = ("失败", "退票", "已退票", "冲正", "已冲正", "已失败")
# 流水侧的退票/失败
PAYMENT_FAILED_STATES: tuple[str, ...] = ("失败", "退票", "已退票", "冲正", "已冲正", "已失败")
# 两侧「钱还没出去」的中间态：台账说已结案、流水还停在待支付，同样是状态差
LEDGER_PENDING_STATES: tuple[str, ...] = (
    "待支付",
    "未支付",
    "待处理",
    "处理中",
    "审核中",
    "在途",
    "已受理",
)
PAYMENT_PENDING_STATES: tuple[str, ...] = (
    "待支付",
    "未支付",
    "待处理",
    "处理中",
    "审核中",
    "在途",
    "已受理",
)

# 结果表列顺序（报告层按这个顺序落 sheet）
DETAIL_COLUMNS: tuple[str, ...] = (
    "对账结果",
    "匹配类型",
    "保单号",
    "赔案号",
    "台账笔数",
    "流水笔数",
    "台账金额",
    "流水金额",
    "差异金额",
    "绝对差异",
    "状态一致",
    "台账行号",
    "流水行号",
    "说明",
)

_EMPTY_KEY_TEXTS = {"", "nan", "none", "null", "<na>", "nat"}
# 「123.0」「-45.00」这类整数形态的文本（导出工具把数字写成了文本时会出现）
_INTEGER_LIKE_TEXT = re.compile(r"[+-]?\d+\.0+")


# =============================================================================
# 内部数据结构
# =============================================================================


@dataclass(frozen=True)
class _SideRow:
    """一侧的一行：来源行号 + 主键（匹配用 tuple）+ 展示用主键 + 金额 + 状态"""

    row_no: int
    key: tuple[str, ...]
    display: tuple[str, ...]
    amount: Decimal
    status: str = ""


# =============================================================================
# 取值归一
# =============================================================================


def _to_decimal(value: Any) -> Optional[Decimal]:
    """把单元格值转成 Decimal；空值/非数字/NaN/Infinity 一律返回 None"""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    text = str(value).strip()
    if text.lower() in _EMPTY_KEY_TEXTS:
        return None
    # 真实台账里常见「1,234.56」「¥1234.56」这类写法
    text = text.replace(",", "").replace("，", "").lstrip("¥￥$")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _to_status(value: Any) -> str:
    """状态取值归一；空值给空串（表示没填）"""
    text = _display_key_part(value)
    return text if text is not None else ""


def _to_key_text(value: Any) -> Optional[str]:
    """主键取值归一（用于匹配）：空值返回 None，数字与数字文本统一成同一个写法

    台账和流水常常一边是数字单元格、一边是文本，同一笔会因此被拆成两条孤岛：

    - Excel 里某列有空格子时整列会变成 ``Float64``，``12345`` 读出来是 ``"12345.0"``；
    - 数字单元格 ``12345`` 与文本 ``"012345"``（前导零补位）写法不同；
    - 19 位单号转成 ``float`` 会变成 ``"1.2345678901234568e+18"``。

    这里把「整数值」统一成不带小数点、不带前导零、不用科学计数法的十进制串，
    非数字文本（如 ``CL9900100``）原样保留。展示用的原始写法另走
    ``_display_key_part``，不丢前导零。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if pd.isna(value):
            return None
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        if value == value.to_integral_value():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if text.lower() in _EMPTY_KEY_TEXTS:
        return None
    # 纯整数文本：去掉前导零与正号，长数字也能精确处理（不经 float）
    stripped = text.lstrip("+")
    if stripped.isdigit():
        return str(int(stripped))
    if stripped.startswith("-") and stripped[1:].isdigit():
        return str(int(stripped))
    # 「123.0」这类整数形态的小数文本也要归一：一侧是数字单元格 123、另一侧是
    # 文本 "123.0"（导出工具把数字写成了文本）时，不归一就会拆成两条孤岛
    if _INTEGER_LIKE_TEXT.fullmatch(stripped):
        return str(int(Decimal(stripped)))
    return text


def _display_key_part(value: Any) -> Optional[str]:
    """主键的展示写法：保留原始文本（含前导零），只去掉首尾空白"""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if text.lower() in _EMPTY_KEY_TEXTS:
        return None
    return text


def _format_key(key: Sequence[str], display: Sequence[str]) -> str:
    """把主键写成人能读的一串（只用于 issues 与日志，匹配用 tuple）"""
    parts = list(display) if display else list(key)
    return " / ".join(parts)


# =============================================================================
# 单侧准备：校验列、拆出有效行、收集脏数据
# =============================================================================


def _require_columns(
    df: pd.DataFrame,
    columns: Sequence[str],
    *,
    side: str,
) -> None:
    """列缺失时抛 InvalidColumnError，报错要写明是哪一侧、缺哪一列

    ``identified_columns`` 必须取**这一侧**的实际列名：两侧是两份文件，
    拿台账的列去解释流水缺列，会让人以为文件里明明有该列。
    """
    missing = [name for name in columns if name not in df.columns]
    if missing:
        raise InvalidColumnError(
            missing,
            identified_columns=[str(name) for name in df.columns],
            expected_columns=list(columns),
            side=side,
        )


def _prepare_side(
    df: pd.DataFrame,
    *,
    side: str,
    key_fields: Sequence[str],
    amount_field: str,
    status_field: Optional[str],
) -> tuple[list[_SideRow], list[dict[str, Any]]]:
    """把一侧 DataFrame 拆成有效行与脏数据清单

    主键为空、金额不可用的行不会抛异常，而是进 issues（带来源行号与原因）。
    来源行号按「表头占第 1 行」计算，与 ``reconciler`` 的口径一致：取 DataFrame
    索引 + 2，而不是 enumerate 的序号 —— 上游做过过滤/重排时，序号会指错行。
    """
    rows: list[_SideRow] = []
    issues: list[dict[str, Any]] = []

    for position, (idx, raw_row) in enumerate(df.iterrows()):
        row_no = _row_number(idx, position)
        key_parts = [_to_key_text(raw_row[name]) for name in key_fields]
        display_parts = [_display_key_part(raw_row[name]) for name in key_fields]
        key_tuple = tuple("" if part is None else part for part in key_parts)
        display_tuple = tuple("" if part is None else part for part in display_parts)
        key_text = _format_key(key_tuple, display_tuple)
        if any(part is None for part in key_parts):
            issues.append(
                {
                    "side": side,
                    "row": row_no,
                    "reason": ISSUE_EMPTY_KEY,
                    "key": key_text,
                    "amount": None,
                }
            )
            continue

        amount = _to_decimal(raw_row[amount_field])
        if amount is None:
            issues.append(
                {
                    "side": side,
                    "row": row_no,
                    "reason": ISSUE_INVALID_AMOUNT,
                    "key": key_text,
                    "amount": str(raw_row[amount_field]),
                }
            )
            continue

        status = _to_status(raw_row[status_field]) if status_field is not None else ""
        rows.append(
            _SideRow(
                row_no=row_no,
                key=key_tuple,
                display=display_tuple,
                amount=amount,
                status=status,
            )
        )

    return rows, issues


def _row_number(index: Any, position: int) -> int:
    """DataFrame 索引 → 表格行号（表头占第 1 行）

    与 ``reconciler`` 的 ``idx + 2`` 同口径。索引不是整数（上游重排、MultiIndex）
    时退化成位置序号 + 2，避免出现 ``TypeError``。
    """
    if isinstance(index, bool):
        return position + 2
    if isinstance(index, (int, float)):
        return int(index) + 2
    return position + 2


def _group(rows: Sequence[_SideRow]) -> dict[tuple[str, ...], list[_SideRow]]:
    """按主键分组（保持首次出现的顺序，报告读起来稳定）"""
    buckets: dict[tuple[str, ...], list[_SideRow]] = {}
    for row in rows:
        buckets.setdefault(row.key, []).append(row)
    return buckets


# =============================================================================
# 汇总模型
# =============================================================================


class CrossCheckSummary(BaseModel):
    """多源对账摘要"""

    key_fields: list[str] = Field(default_factory=list, description="本次使用的主键字段")
    ledger_records: int = Field(default=0, description="台账原始行数")
    payment_records: int = Field(default=0, description="流水原始行数")
    ledger_valid_records: int = Field(default=0, description="台账参与对账的行数")
    payment_valid_records: int = Field(default=0, description="流水参与对账的行数")
    invalid_records: int = Field(default=0, description="主键/金额不可用、未参与对账的行数")

    matched_groups: int = 0
    amount_diff_groups: int = 0
    ledger_only_groups: int = 0
    payment_only_groups: int = 0
    status_diff_groups: int = 0

    one_to_one_groups: int = 0
    one_to_many_groups: int = 0
    many_to_one_groups: int = 0
    many_to_many_groups: int = 0

    ledger_amount_total: Decimal = Field(default=Decimal("0.00"), description="Σ台账金额（有效行）")
    payment_amount_total: Decimal = Field(
        default=Decimal("0.00"), description="Σ流水金额（有效行）"
    )
    diff_amount_total: Decimal = Field(
        default=Decimal("0.00"), description="Σ差异金额（带符号：台账 − 流水）"
    )
    ledger_only_amount: Decimal = Field(
        default=Decimal("0.00"), description="只记未付金额合计（正数）"
    )
    payment_only_amount: Decimal = Field(
        default=Decimal("0.00"), description="只付未记金额合计（正数）"
    )

    tolerance_absolute: Decimal = Field(default=Decimal("0.01"), description="本次使用的绝对容差")
    tolerance_ratio: Decimal = Field(default=Decimal("0.001"), description="本次使用的相对容差")

    identity_holds: bool = Field(default=True, description="Σ台账 == Σ流水 + Σ差异 是否成立")
    identity_gap: Decimal = Field(default=Decimal("0.00"), description="恒等式两边的差额")

    issues: list[dict[str, Any]] = Field(
        default_factory=list, description="脏数据明细（哪一侧、第几行、什么原因）"
    )
    details: list[dict[str, Any]] = Field(default_factory=list, description="逐组对账明细")


# =============================================================================
# 主流程
# =============================================================================


def _resolve_keys(
    ledger_df: pd.DataFrame,
    payment_df: pd.DataFrame,
    profile: Optional[MappingProfile],
    keys: Optional[Sequence[str]],
) -> tuple[str, ...]:
    """决定主键：显式传入 > profile 显式声明 > 默认「保单号 + 赔案号」

    只有 profile **显式声明了非空** ``primary_key`` 才用它（含最常见的单键
    ``["保单号"]``）。``MappingProfile.primary_key`` 的默认值是空元组，
    表示「未配置」；否则只改容差、encoding 的 profile 也会把主键悄悄降成单键，
    同一保单的多个赔案就被合并成一组。
    """
    if keys:
        return tuple(keys)

    if profile is not None and profile.primary_key:
        _require_columns(ledger_df, profile.primary_key, side="台账")
        _require_columns(payment_df, profile.primary_key, side="流水")
        return tuple(profile.primary_key)

    # 缺一个默认键就降级成单键，会把「配置问题」伪装成「金额对不上」，所以报错。
    # 两侧分别检查：只报一侧会漏掉另一侧缺的键（原实现用 or 短路，实测吞掉流水缺的那个）
    _require_columns(ledger_df, DEFAULT_KEY_FIELDS, side="台账")
    _require_columns(payment_df, DEFAULT_KEY_FIELDS, side="流水")
    return DEFAULT_KEY_FIELDS


def _top_repeat(rows: Sequence[_SideRow]) -> tuple[int, Optional[Decimal], list[int]]:
    """同一组里出现次数最多的那个金额：笔数、金额、以及它落在哪几行

    一对多本身是正常形态（分期打款、退票后重付），只有「多笔金额一模一样」
    才像重复记账。返回 ``(笔数, 金额, 行号列表)``；笔数为 1 表示没有同额重复，
    金额为 ``None`` 表示这一侧没有有效行。

    金额与行号必须跟着笔数一起返回：组里可能是 ``100 + 450 + 450``，此时
    「重复」的是 450、重复 2 笔、落在第 3、4 行，而不是「3 笔全是 100」——
    只报笔数会把原因说错，只报组里第一行会把位置指到不相干的那一行
    （实测过这两个错法）。
    """
    if not rows:
        return 0, None, []
    counts: dict[Decimal, int] = {}
    for row in rows:
        counts[row.amount] = counts.get(row.amount, 0) + 1
    amount = max(counts, key=lambda value: counts[value])
    rows_no = [row.row_no for row in rows if row.amount == amount]
    return counts[amount], amount, rows_no


def _match_type(ledger_count: int, payment_count: int) -> str:
    if payment_count == 0:
        return MATCH_LEDGER_ONLY
    if ledger_count == 0:
        return MATCH_PAYMENT_ONLY
    if ledger_count == 1 and payment_count == 1:
        return MATCH_ONE_TO_ONE
    if ledger_count == 1:
        return MATCH_ONE_TO_MANY
    if payment_count == 1:
        return MATCH_MANY_TO_ONE
    return MATCH_MANY_TO_MANY


def _status_conflict(ledger: Sequence[_SideRow], payment: Sequence[_SideRow]) -> bool:
    """状态差：两侧对「这笔钱到底付没付」说法相反

    四个方向都算：

    - 台账说已结案/已赔付，流水却是失败/退票/冲正 —— 钱没出去但账上结了；
    - 台账说退票/失败，流水却是已赔付 —— 钱出去了但账上还挂着没付；
    - 台账说已结案，流水还停在待支付/处理中 —— 账上结了但钱其实还没付；
    - 台账还停在待支付/处理中，流水却已成功 —— 钱付了但账上没销账。

    issue #32 的原文是「台账『已结案』但流水『退票/失败』，**或反之**」，
    只判一个方向会把后者漏成「一致」；后两个方向是实务里最常见的两种错，
    只判「极端相反」的组合同样会漏成「一致」（实测：已结案 + 待支付
    原先报「状态一致=是」）。
    """
    ledger_closed = any(row.status in LEDGER_CLOSED_STATES for row in ledger)
    ledger_failed = any(row.status in LEDGER_FAILED_STATES for row in ledger)
    ledger_pending = any(row.status in LEDGER_PENDING_STATES for row in ledger)
    payment_closed = any(row.status in PAYMENT_CLOSED_STATES for row in payment)
    payment_failed = any(row.status in PAYMENT_FAILED_STATES for row in payment)
    payment_pending = any(row.status in PAYMENT_PENDING_STATES for row in payment)
    return (
        (ledger_closed and payment_failed)
        or (ledger_failed and payment_closed)
        or (ledger_closed and payment_pending)
        or (ledger_pending and payment_closed)
    )


def _status_conflict_note(ledger: Sequence[_SideRow], payment: Sequence[_SideRow]) -> str:
    """给出能读懂的状态差说明（哪个方向）"""
    ledger_closed = any(row.status in LEDGER_CLOSED_STATES for row in ledger)
    ledger_failed = any(row.status in LEDGER_FAILED_STATES for row in ledger)
    ledger_pending = any(row.status in LEDGER_PENDING_STATES for row in ledger)
    payment_closed = any(row.status in PAYMENT_CLOSED_STATES for row in payment)
    payment_failed = any(row.status in PAYMENT_FAILED_STATES for row in payment)
    payment_pending = any(row.status in PAYMENT_PENDING_STATES for row in payment)
    if ledger_closed and payment_failed:
        return "台账已结案但流水失败/退票"
    if ledger_failed and payment_closed:
        return "台账退票/失败但流水已赔付"
    if ledger_closed and payment_pending:
        return "台账已结案但流水还没付（待支付/处理中）"
    if ledger_pending and payment_closed:
        return "台账还挂着待支付/处理中，但流水已成功（账上未销账）"
    return "两侧状态不一致"


def _status_comparable(ledger: Sequence[_SideRow], payment: Sequence[_SideRow]) -> bool:
    """两侧都填了状态才有「一致 / 不一致」可言

    状态列存在、但某一侧整组都是空值（没填）时，原实现直接判 ``not conflict``
    为 True，输出「状态一致=是」—— 其实一行都没比较过，等于给了一份它给不出
    的保证。这时应当报 ``—``。
    """
    return any(row.status for row in ledger) and any(row.status for row in payment)


def crosscheck(
    ledger_df: pd.DataFrame,
    payment_df: pd.DataFrame,
    profile: Optional[Union[str, Path, MappingProfile]] = None,
    keys: Optional[Sequence[str]] = None,
    ledger_amount_field: str = DEFAULT_AMOUNT_FIELD,
    payment_amount_field: str = DEFAULT_AMOUNT_FIELD,
    status_field: Optional[str] = DEFAULT_STATUS_FIELD,
    tolerance_absolute: Optional[Decimal] = None,
    tolerance_ratio: Optional[Decimal] = None,
) -> tuple[pd.DataFrame, CrossCheckSummary]:
    """台账 ↔ 支付流水多源对账

    Args:
        ledger_df: 台账（已按 profile 映射成标准列）
        payment_df: 支付流水（同上）
        profile: 映射 profile；声明了 ``tolerance_absolute`` / ``tolerance_ratio``
            和非空 ``primary_key`` 时生效（空 ``primary_key`` 表示未配置，回落默认键）
        keys: 主键字段；留空按 profile.primary_key → ``保单号 + 赔案号`` 推断
        ledger_amount_field: 台账侧金额列，默认 ``实际赔付金额``
        payment_amount_field: 流水侧金额列，默认 ``实际赔付金额``
        status_field: 状态列；两侧都有才比较，传 None 关闭状态检查
        tolerance_absolute: 绝对容差；留空按 profile 再按全局配置
        tolerance_ratio: 相对容差；留空按 profile 再按全局配置

    Returns:
        (逐组对账明细 DataFrame, 对账摘要)

    Raises:
        InvalidColumnError: 主键列或金额列缺失（这是配置问题，不是脏数据）
    """
    active_profile = load_profile(profile) if profile is not None else None

    key_fields = _resolve_keys(ledger_df, payment_df, active_profile, keys)

    status_columns = (
        [status_field]
        if status_field is not None
        and status_field in ledger_df.columns
        and status_field in payment_df.columns
        else []
    )
    if status_field is not None and not status_columns:
        # 状态列只在一边有（或都没有）时状态检查会静默关闭，报告里只剩「—」，
        # 看起来像「检查过了没问题」。这是配置问题，必须说出来。
        missing_sides = [
            side
            for side, frame in (("台账", ledger_df), ("流水", payment_df))
            if status_field not in frame.columns
        ]
        logger.warning(
            "状态检查已关闭：%s 里没有状态列 %r（台账列=%s，流水列=%s）",
            " 和 ".join(missing_sides),
            status_field,
            list(ledger_df.columns),
            list(payment_df.columns),
        )
    _require_columns(ledger_df, list(key_fields) + [ledger_amount_field], side="台账")
    _require_columns(payment_df, list(key_fields) + [payment_amount_field], side="流水")

    ledger_rows, ledger_issues = _prepare_side(
        ledger_df,
        side="台账",
        key_fields=key_fields,
        amount_field=ledger_amount_field,
        status_field=status_columns[0] if status_columns else None,
    )
    payment_rows, payment_issues = _prepare_side(
        payment_df,
        side="流水",
        key_fields=key_fields,
        amount_field=payment_amount_field,
        status_field=status_columns[0] if status_columns else None,
    )

    absolute_tolerance = (
        tolerance_absolute
        if tolerance_absolute is not None
        else (active_profile.tolerance_absolute if active_profile is not None else None)
    )
    ratio_tolerance = (
        tolerance_ratio
        if tolerance_ratio is not None
        else (active_profile.tolerance_ratio if active_profile is not None else None)
    )
    effective_absolute = (
        settings.insurance.tolerance_absolute if absolute_tolerance is None else absolute_tolerance
    )
    effective_ratio = (
        settings.insurance.tolerance_ratio if ratio_tolerance is None else ratio_tolerance
    )

    ledger_groups = _group(ledger_rows)
    payment_groups = _group(payment_rows)

    # 先出台账的键，再出只在流水里出现的键，顺序稳定
    ordered_keys = list(ledger_groups)
    ordered_keys.extend(key for key in payment_groups if key not in ledger_groups)

    issues: list[dict[str, Any]] = ledger_issues + payment_issues
    detail_rows: list[dict[str, Any]] = []

    counters = {
        RESULT_MATCHED: 0,
        RESULT_AMOUNT_DIFF: 0,
        RESULT_LEDGER_ONLY: 0,
        RESULT_PAYMENT_ONLY: 0,
        RESULT_STATUS_DIFF: 0,
    }
    match_counters = {
        MATCH_ONE_TO_ONE: 0,
        MATCH_ONE_TO_MANY: 0,
        MATCH_MANY_TO_ONE: 0,
        MATCH_MANY_TO_MANY: 0,
    }
    ledger_total = Decimal("0.00")
    payment_total = Decimal("0.00")
    diff_total = Decimal("0.00")
    ledger_only_amount = Decimal("0.00")
    payment_only_amount = Decimal("0.00")

    # 恒等式的左边必须独立求和，不能也用逐组差值累加：
    # 那样 identity_gap 按构造永远为 0，测试也就永远不可能失败。
    ledger_row_total = sum((row.amount for row in ledger_rows), start=Decimal("0.00"))
    payment_row_total = sum((row.amount for row in payment_rows), start=Decimal("0.00"))

    for key in ordered_keys:
        ledger_items = ledger_groups.get(key, [])
        payment_items = payment_groups.get(key, [])

        ledger_amount = sum((item.amount for item in ledger_items), start=Decimal("0.00"))
        payment_amount = sum((item.amount for item in payment_items), start=Decimal("0.00"))
        diff = ledger_amount - payment_amount
        base_amount = ledger_amount if ledger_items else payment_amount
        tolerance = tolerance_for(base_amount, absolute_tolerance, ratio_tolerance)

        match_type = _match_type(len(ledger_items), len(payment_items))
        status_consistent: Optional[bool] = None
        note_parts: list[str] = []

        if ledger_items and payment_items:
            if abs(diff) < tolerance:
                result = RESULT_MATCHED
            else:
                result = RESULT_AMOUNT_DIFF
                note_parts.append(f"金额差超出容差 {tolerance}")
            if status_columns and _status_comparable(ledger_items, payment_items):
                conflict = _status_conflict(ledger_items, payment_items)
                status_consistent = not conflict
                if conflict and result == RESULT_MATCHED:
                    result = RESULT_STATUS_DIFF
                    note_parts.append(_status_conflict_note(ledger_items, payment_items))
                elif conflict:
                    note_parts.append(
                        f"状态也不一致（{_status_conflict_note(ledger_items, payment_items)}）"
                    )
        elif ledger_items:
            result = RESULT_LEDGER_ONLY
            # 只有一侧有行，谈不上「状态一致」，输出 — 而不是「是」
            status_consistent = None
            note_parts.append("台账有记录、流水无对应付款")
            ledger_only_amount += ledger_amount
        else:
            result = RESULT_PAYMENT_ONLY
            status_consistent = None
            note_parts.append("流水有付款、台账无对应记录（可能是账外赔付）")
            payment_only_amount += payment_amount

        # 同侧多行：金额不等的合并是正常形态（分期打款、退票重付），只写进说明；
        # 只有「多行金额完全相同」才当成重复记账嫌疑报进 issues，避免把正常分期
        # 也标成疑点、把真疑点淹没
        ledger_repeat, ledger_repeat_amount, ledger_repeat_rows = _top_repeat(ledger_items)
        payment_repeat, payment_repeat_amount, payment_repeat_rows = _top_repeat(payment_items)
        if ledger_repeat > 1:
            issues.append(
                {
                    "side": "台账",
                    "row": ledger_repeat_rows[0],
                    "rows": ledger_repeat_rows,
                    "reason": ISSUE_DUPLICATE_KEY,
                    "key": _format_key(key, ledger_items[0].display),
                    "amount": str(ledger_repeat_amount),
                    "detail": (
                        f"同一主键在台账出现 {len(ledger_items)} 次，其中 "
                        f"{ledger_repeat} 笔金额完全相同（{ledger_repeat_amount}），"
                        f"可能是重复记账，请人工确认"
                    ),
                }
            )
            note_parts.append(f"台账重复记账嫌疑 {ledger_repeat} 笔同额")
        elif len(ledger_items) > 1:
            note_parts.append(f"台账分 {len(ledger_items)} 笔合并")
        if payment_repeat > 1:
            issues.append(
                {
                    "side": "流水",
                    "row": payment_repeat_rows[0],
                    "rows": payment_repeat_rows,
                    "reason": ISSUE_DUPLICATE_KEY,
                    "key": _format_key(key, payment_items[0].display),
                    "amount": str(payment_repeat_amount),
                    "detail": (
                        f"同一主键在流水出现 {len(payment_items)} 次，其中 "
                        f"{payment_repeat} 笔金额完全相同（{payment_repeat_amount}），"
                        f"可能是重复付款或同额分期，请人工确认"
                    ),
                }
            )
            note_parts.append(f"流水重复记账嫌疑 {payment_repeat} 笔同额")
        elif len(payment_items) > 1:
            note_parts.append(f"流水分 {len(payment_items)} 笔支付")

        counters[result] += 1
        if match_type in match_counters:
            match_counters[match_type] += 1

        ledger_total += ledger_amount
        payment_total += payment_amount
        diff_total += diff

        # 主键是 tuple，直接按位置取，不再拼字符串再 split（键里含分隔符会串列）
        detail_row: dict[str, Any] = {
            "对账结果": result,
            "匹配类型": match_type,
        }
        display_parts = (
            ledger_items[0].display if ledger_items else (payment_items[0].display or key)
        )
        for index, name in enumerate(key_fields):
            detail_row[name] = display_parts[index] if index < len(display_parts) else ""
        detail_row.update(
            {
                "台账笔数": len(ledger_items),
                "流水笔数": len(payment_items),
                "台账金额": ledger_amount,
                "流水金额": payment_amount,
                "差异金额": diff,
                "绝对差异": abs(diff),
                "状态一致": (
                    "—" if status_consistent is None else ("是" if status_consistent else "否")
                ),
                "台账行号": ",".join(str(item.row_no) for item in ledger_items),
                "流水行号": ",".join(str(item.row_no) for item in payment_items),
                "说明": "；".join(note_parts),
            }
        )
        detail_rows.append(detail_row)

    # 恒等式两边各自独立求：左边是逐行原始金额，右边是分组累计 + 逐组差值。
    # 分组若漏行、重复计数，两边就会不等 —— 否则拿 diff_total 回头验自己，
    # identity_gap 按构造永远是 0，这条校验等于没有。
    identity_gap = ledger_row_total - payment_row_total - diff_total
    identity_holds = identity_gap == 0
    if not identity_holds:
        logger.error(
            "多源对账恒等式不成立: 逐行Σ台账=%s, 逐行Σ流水=%s, 分组Σ差异=%s, 差额=%s",
            ledger_row_total,
            payment_row_total,
            diff_total,
            identity_gap,
        )

    summary = CrossCheckSummary(
        key_fields=list(key_fields),
        ledger_records=len(ledger_df),
        payment_records=len(payment_df),
        ledger_valid_records=len(ledger_rows),
        payment_valid_records=len(payment_rows),
        invalid_records=len(ledger_issues) + len(payment_issues),
        matched_groups=counters[RESULT_MATCHED],
        amount_diff_groups=counters[RESULT_AMOUNT_DIFF],
        ledger_only_groups=counters[RESULT_LEDGER_ONLY],
        payment_only_groups=counters[RESULT_PAYMENT_ONLY],
        status_diff_groups=counters[RESULT_STATUS_DIFF],
        one_to_one_groups=match_counters[MATCH_ONE_TO_ONE],
        one_to_many_groups=match_counters[MATCH_ONE_TO_MANY],
        many_to_one_groups=match_counters[MATCH_MANY_TO_ONE],
        many_to_many_groups=match_counters[MATCH_MANY_TO_MANY],
        ledger_amount_total=ledger_total,
        payment_amount_total=payment_total,
        diff_amount_total=diff_total,
        ledger_only_amount=ledger_only_amount,
        payment_only_amount=payment_only_amount,
        tolerance_absolute=effective_absolute,
        tolerance_ratio=effective_ratio,
        identity_holds=identity_holds,
        identity_gap=identity_gap,
        issues=issues,
        details=detail_rows,
    )

    logger.info(
        "多源对账完成: 台账=%s(有效 %s) 流水=%s(有效 %s) 脏数据=%s | "
        "一致=%s 金额差=%s 只记未付=%s 只付未记=%s 状态差=%s",
        summary.ledger_records,
        summary.ledger_valid_records,
        summary.payment_records,
        summary.payment_valid_records,
        summary.invalid_records,
        summary.matched_groups,
        summary.amount_diff_groups,
        summary.ledger_only_groups,
        summary.payment_only_groups,
        summary.status_diff_groups,
    )

    # 自定义主键可能不在默认列里，补在「对账结果」「匹配类型」之后
    output_columns = list(DETAIL_COLUMNS[:2])
    output_columns.extend(name for name in key_fields if name not in DETAIL_COLUMNS)
    output_columns.extend(name for name in DETAIL_COLUMNS[2:] if name not in output_columns)
    result_df = pd.DataFrame(detail_rows, columns=output_columns)
    return result_df, summary

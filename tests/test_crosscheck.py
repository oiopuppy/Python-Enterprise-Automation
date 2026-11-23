"""
多源对账引擎测试 — 台账 ↔ 支付流水

覆盖 issue #32 的验收点：
- 四类结果（matched / amount_diff / ledger_only / payment_only）各能定位到源行
- 恒等式 Σ台账 == Σ流水 + Σ差异（Decimal 精确比较）
- 一对多分摊（1 条台账对 3 条流水）
- 脏数据（主键为空、金额不可用、重复主键）不抛异常、落进 issues
- 状态差（台账已结案、流水退票）
"""

from decimal import Decimal

import pandas as pd
import pytest

from insurance_audit.audit.crosscheck import (
    DETAIL_COLUMNS,
    ISSUE_DUPLICATE_KEY,
    ISSUE_EMPTY_KEY,
    ISSUE_INVALID_AMOUNT,
    MATCH_LEDGER_ONLY,
    MATCH_MANY_TO_MANY,
    MATCH_MANY_TO_ONE,
    MATCH_ONE_TO_MANY,
    MATCH_ONE_TO_ONE,
    MATCH_PAYMENT_ONLY,
    RESULT_AMOUNT_DIFF,
    RESULT_LEDGER_ONLY,
    RESULT_MATCHED,
    RESULT_PAYMENT_ONLY,
    RESULT_STATUS_DIFF,
    crosscheck,
)
from insurance_audit.utils.config import MappingProfile
from insurance_audit.utils.exceptions import InvalidColumnError


def _ledger(rows: list[dict[str, object]]) -> pd.DataFrame:
    """构造台账 DataFrame（默认按 保单号 + 赔案号 匹配）"""
    return pd.DataFrame(rows, columns=["保单号", "赔案号", "实际赔付金额", "案件状态"])


def _payment(rows: list[dict[str, object]]) -> pd.DataFrame:
    """构造支付流水 DataFrame"""
    return pd.DataFrame(rows, columns=["保单号", "赔案号", "实际赔付金额", "案件状态"])


class TestFourResultKinds:
    """四类结果：一致、金额差、只记未付、只付未记"""

    def test_matched_rows_are_marked_and_located(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "成功"}]
        )

        detail, summary = crosscheck(ledger, payment)

        assert len(detail) == 1
        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_MATCHED
        assert row["匹配类型"] == MATCH_ONE_TO_ONE
        assert row["台账行号"] == "2"
        assert row["流水行号"] == "2"
        assert summary.matched_groups == 1
        assert summary.diff_amount_total == Decimal("0.00")

    def test_amount_diff_keeps_signed_difference(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 800.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 850.00, "案件状态": "成功"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_AMOUNT_DIFF
        # 台账 − 流水 = -50，带符号，方便财务看出是多付还是少付
        assert row["差异金额"] == Decimal("-50.00")
        assert row["绝对差异"] == Decimal("50.00")
        assert summary.amount_diff_groups == 1
        assert summary.diff_amount_total == Decimal("-50.00")

    def test_ledger_only_is_unpaid(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment([])

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_LEDGER_ONLY
        assert row["匹配类型"] == MATCH_LEDGER_ONLY
        assert row["台账行号"] == "2"
        assert row["流水行号"] == ""
        assert summary.ledger_only_groups == 1
        assert summary.ledger_only_amount == Decimal("300.00")

    def test_payment_only_is_off_book_payment(self) -> None:
        ledger = _ledger([])
        payment = _payment(
            [{"保单号": "CL9900999", "赔案号": "C999", "实际赔付金额": 700.00, "案件状态": "成功"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_PAYMENT_ONLY
        assert row["匹配类型"] == MATCH_PAYMENT_ONLY
        assert row["流水行号"] == "2"
        assert summary.payment_only_groups == 1
        assert summary.payment_only_amount == Decimal("700.00")

    def test_all_four_kinds_in_one_run(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900001",
                    "赔案号": "C1",
                    "实际赔付金额": 100.00,
                    "案件状态": "已结案",
                },
                {
                    "保单号": "CL9900002",
                    "赔案号": "C2",
                    "实际赔付金额": 200.00,
                    "案件状态": "已结案",
                },
                {
                    "保单号": "CL9900003",
                    "赔案号": "C3",
                    "实际赔付金额": 300.00,
                    "案件状态": "已结案",
                },
            ]
        )
        payment = _payment(
            [
                {"保单号": "CL9900001", "赔案号": "C1", "实际赔付金额": 100.00, "案件状态": "成功"},
                {"保单号": "CL9900002", "赔案号": "C2", "实际赔付金额": 250.00, "案件状态": "成功"},
                {"保单号": "CL9900004", "赔案号": "C4", "实际赔付金额": 400.00, "案件状态": "成功"},
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        results = list(detail["对账结果"])
        assert results == [
            RESULT_MATCHED,
            RESULT_AMOUNT_DIFF,
            RESULT_LEDGER_ONLY,
            RESULT_PAYMENT_ONLY,
        ]
        assert summary.matched_groups == 1
        assert summary.amount_diff_groups == 1
        assert summary.ledger_only_groups == 1
        assert summary.payment_only_groups == 1
        # 台账 600 - 流水 750 = -150
        assert summary.diff_amount_total == Decimal("-150.00")


class TestIdentity:
    """恒等式 Σ台账 == Σ流水 + Σ差异"""

    @staticmethod
    def _assert_identity(summary: object) -> None:
        ledger_total = summary.ledger_amount_total  # type: ignore[attr-defined]
        payment_total = summary.payment_amount_total  # type: ignore[attr-defined]
        diff_total = summary.diff_amount_total  # type: ignore[attr-defined]
        assert isinstance(ledger_total, Decimal)
        assert isinstance(payment_total, Decimal)
        assert isinstance(diff_total, Decimal)
        assert ledger_total == payment_total + diff_total
        assert summary.identity_holds is True  # type: ignore[attr-defined]
        assert summary.identity_gap == Decimal("0.00")  # type: ignore[attr-defined]

    def test_identity_holds_across_mixed_results(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900001",
                    "赔案号": "C1",
                    "实际赔付金额": 100.10,
                    "案件状态": "已结案",
                },
                {
                    "保单号": "CL9900002",
                    "赔案号": "C2",
                    "实际赔付金额": 200.20,
                    "案件状态": "已结案",
                },
                {
                    "保单号": "CL9900003",
                    "赔案号": "C3",
                    "实际赔付金额": 300.30,
                    "案件状态": "已结案",
                },
            ]
        )
        payment = _payment(
            [
                {"保单号": "CL9900001", "赔案号": "C1", "实际赔付金额": 100.10, "案件状态": "成功"},
                {"保单号": "CL9900002", "赔案号": "C2", "实际赔付金额": 250.25, "案件状态": "成功"},
                {"保单号": "CL9900009", "赔案号": "C9", "实际赔付金额": 400.40, "案件状态": "成功"},
            ]
        )

        _, summary = crosscheck(ledger, payment)

        self._assert_identity(summary)

    def test_identity_holds_with_one_to_many(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 900.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
            ]
        )

        _, summary = crosscheck(ledger, payment)

        self._assert_identity(summary)

    def test_decimal_precision_not_float(self) -> None:
        """0.1 + 0.2 这类浮点陷阱必须不出现"""
        ledger = _ledger(
            [
                {"保单号": "CL9900001", "赔案号": "C1", "实际赔付金额": Decimal("0.10")},
                {"保单号": "CL9900002", "赔案号": "C2", "实际赔付金额": Decimal("0.20")},
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900001", "赔案号": "C1", "实际赔付金额": Decimal("0.30")}]
        )

        _, summary = crosscheck(ledger, payment)

        assert summary.ledger_amount_total == Decimal("0.30")
        assert summary.payment_amount_total == Decimal("0.30")
        assert summary.diff_amount_total == Decimal("0.00")
        self._assert_identity(summary)


class TestOneToMany:
    """一对多分摊与合并分组"""

    def test_one_ledger_three_payments(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 900.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        assert len(detail) == 1, "同一主键必须合并成一行"
        row = detail.iloc[0]
        assert row["匹配类型"] == MATCH_ONE_TO_MANY
        assert row["台账笔数"] == 1
        assert row["流水笔数"] == 3
        assert row["台账金额"] == Decimal("900.00")
        assert row["流水金额"] == Decimal("900.00")
        assert row["对账结果"] == RESULT_MATCHED
        assert row["流水行号"] == "2,3,4"
        assert summary.one_to_many_groups == 1
        # 一对多本身是「重复主键」疑点，要能看见
        duplicates = [item for item in summary.issues if item["reason"] == ISSUE_DUPLICATE_KEY]
        assert len(duplicates) == 1
        assert duplicates[0]["side"] == "流水"

    def test_partial_payment_is_amount_diff(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 900.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 300.00,
                    "案件状态": "成功",
                },
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["匹配类型"] == MATCH_ONE_TO_MANY
        assert row["对账结果"] == RESULT_AMOUNT_DIFF
        assert row["差异金额"] == Decimal("300.00")
        assert summary.ledger_only_amount == Decimal("0.00"), "部分付款不算只记未付"

    def test_many_to_one_and_many_to_many(self) -> None:
        ledger = _ledger(
            [
                # 一对一
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 150.00},
                # 多对一：两条台账（100 + 150）对一条流水（250）
                {"保单号": "CL9900200", "赔案号": "C002", "实际赔付金额": 100.00},
                {"保单号": "CL9900200", "赔案号": "C002", "实际赔付金额": 150.00},
                # 多对多：两条台账对两条流水
                {"保单号": "CL9900300", "赔案号": "C003", "实际赔付金额": 100.00},
                {"保单号": "CL9900300", "赔案号": "C003", "实际赔付金额": 100.00},
            ]
        )
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 150.00},
                {"保单号": "CL9900200", "赔案号": "C002", "实际赔付金额": 250.00},
                {"保单号": "CL9900300", "赔案号": "C003", "实际赔付金额": 100.00},
                {"保单号": "CL9900300", "赔案号": "C003", "实际赔付金额": 100.00},
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        by_key = {row["保单号"]: row for _, row in detail.iterrows()}
        assert by_key["CL9900100"]["匹配类型"] == MATCH_ONE_TO_ONE
        assert by_key["CL9900200"]["匹配类型"] == MATCH_MANY_TO_ONE
        assert by_key["CL9900300"]["匹配类型"] == MATCH_MANY_TO_MANY
        assert summary.one_to_one_groups == 1
        assert summary.many_to_one_groups == 1
        assert summary.many_to_many_groups == 1


class TestDirtyData:
    """脏数据必须落进结果并标原因，不能抛异常"""

    def test_empty_key_is_reported_not_raised(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 200.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 200.00}])

        detail, summary = crosscheck(ledger, payment)

        empty_key_issues = [item for item in summary.issues if item["reason"] == ISSUE_EMPTY_KEY]
        assert len(empty_key_issues) == 1
        assert empty_key_issues[0]["side"] == "台账"
        assert empty_key_issues[0]["row"] == 2
        assert summary.invalid_records == 1
        assert summary.ledger_valid_records == 1
        assert len(detail) == 1

    def test_null_amount_is_reported(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": None},
                {"保单号": "CL9900101", "赔案号": "C002", "实际赔付金额": 100.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900101", "赔案号": "C002", "实际赔付金额": 100.00}])

        _, summary = crosscheck(ledger, payment)

        amount_issues = [item for item in summary.issues if item["reason"] == ISSUE_INVALID_AMOUNT]
        assert len(amount_issues) == 1
        assert amount_issues[0]["row"] == 2
        assert summary.invalid_records == 1

    def test_non_numeric_amount_is_reported(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": "待核赔"},
                {"保单号": "CL9900101", "赔案号": "C002", "实际赔付金额": 100.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900101", "赔案号": "C002", "实际赔付金额": 100.00}])

        _, summary = crosscheck(ledger, payment)

        assert any(item["reason"] == ISSUE_INVALID_AMOUNT for item in summary.issues)
        assert summary.invalid_records == 1

    def test_duplicate_key_in_ledger_is_flagged(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 200.00}])

        detail, summary = crosscheck(ledger, payment)

        duplicates = [
            item
            for item in summary.issues
            if item["reason"] == ISSUE_DUPLICATE_KEY and item["side"] == "台账"
        ]
        assert len(duplicates) == 1
        assert duplicates[0]["row"] == 2
        assert "台账重复主键" in str(detail.iloc[0]["说明"])

    def test_dirty_rows_do_not_enter_identity(self) -> None:
        """脏数据既不算进台账合计，也不算进流水合计"""
        ledger = _ledger(
            [
                {"保单号": "", "赔案号": "", "实际赔付金额": 999.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])

        _, summary = crosscheck(ledger, payment)

        assert summary.ledger_amount_total == Decimal("100.00")
        assert (
            summary.ledger_amount_total == summary.payment_amount_total + summary.diff_amount_total
        )


class TestStatusConsistency:
    """状态一致性：台账已结案、流水退票"""

    def test_closed_ledger_with_failed_payment_is_status_diff(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "退票"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_STATUS_DIFF
        assert row["状态一致"] == "否"
        assert summary.status_diff_groups == 1
        assert summary.matched_groups == 0

    def test_normal_status_keeps_matched(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "成功"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_MATCHED
        assert row["状态一致"] == "是"
        assert summary.status_diff_groups == 0

    def test_status_check_can_be_disabled(self) -> None:
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "退票"}]
        )

        detail, summary = crosscheck(ledger, payment, status_field=None)

        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED
        assert detail.iloc[0]["状态一致"] == "—"
        assert summary.status_diff_groups == 0


class TestKeyConfiguration:
    """主键与容差可配"""

    def test_default_key_is_policy_and_case(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C002", "实际赔付金额": 200.00},
            ]
        )
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C002", "实际赔付金额": 200.00},
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        assert summary.key_fields == ["保单号", "赔案号"]
        assert len(detail) == 2, "同一保单不同赔案必须分开"
        assert summary.matched_groups == 2

    def test_explicit_single_key_merges_rows(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C002", "实际赔付金额": 200.00},
            ]
        )
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 300.00},
            ]
        )

        detail, summary = crosscheck(ledger, payment, keys=["保单号"])

        assert summary.key_fields == ["保单号"]
        assert len(detail) == 1
        assert detail.iloc[0]["台账笔数"] == 2
        assert detail.iloc[0]["台账金额"] == Decimal("300.00")
        assert summary.matched_groups == 1

    def test_profile_tolerance_overrides_global(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1000.00}])
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1005.00}])
        profile = MappingProfile(tolerance_absolute=Decimal("10"))

        detail, summary = crosscheck(ledger, payment, profile=profile)

        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED
        assert summary.tolerance_absolute == Decimal("10")

    def test_explicit_tolerance_beats_profile(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1000.00}])
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1005.00}])
        profile = MappingProfile(tolerance_absolute=Decimal("10"))

        detail, _ = crosscheck(ledger, payment, profile=profile, tolerance_absolute=Decimal("1"))

        assert detail.iloc[0]["对账结果"] == RESULT_AMOUNT_DIFF

    def test_missing_amount_column_raises_with_column_name(self) -> None:
        ledger = pd.DataFrame({"保单号": ["CL9900100"], "赔案号": ["C001"]})
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])

        with pytest.raises(InvalidColumnError) as excinfo:
            crosscheck(ledger, payment)

        assert "实际赔付金额" in str(excinfo.value)

    def test_missing_key_columns_raise(self) -> None:
        ledger = pd.DataFrame({"金额": [100.00]})
        payment = pd.DataFrame({"金额": [100.00]})

        with pytest.raises(InvalidColumnError):
            crosscheck(ledger, payment)


class TestOutputShape:
    """输出 DataFrame 的列与类型约定"""

    def test_detail_columns_are_stable(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])

        detail, _ = crosscheck(ledger, payment)

        assert list(detail.columns) == list(DETAIL_COLUMNS)
        assert detail["台账金额"].dtype == object, "金额必须是 Decimal，不能退化成 float"
        assert isinstance(detail.iloc[0]["台账金额"], Decimal)

    def test_empty_inputs_return_empty_result(self) -> None:
        detail, summary = crosscheck(_ledger([]), _payment([]))

        assert detail.empty
        assert summary.matched_groups == 0
        assert summary.identity_holds is True
        assert summary.ledger_amount_total == Decimal("0.00")


class TestMockDataIntegration:
    """用 --generate-mock 的数据造两表样例跑通"""

    def test_generate_mock_data_can_be_reconciled(self, tmp_path: object) -> None:
        from pathlib import Path

        from insurance_audit.data.generator import generate_mock_data
        from insurance_audit.data.reader import read_table

        workdir = Path(str(tmp_path))
        ledger_path = workdir / "ledger.xlsx"

        generate_mock_data(num_records=20, output_file=str(ledger_path), anomaly_ratio=0.0, seed=7)
        ledger = read_table(ledger_path).copy()

        # 造支付流水：15 条按台账全额支付，3 条少付 100，2 条只在流水里
        payment_rows = []
        for index, row in ledger.head(15).iterrows():
            payment_rows.append(
                {
                    "保单号": row["保单号"],
                    "赔案号": f"CASE{index + 1:03d}",
                    "实际赔付金额": row["实际赔付金额"],
                    "案件状态": "成功",
                }
            )
        for offset, (_, row) in enumerate(ledger.iloc[15:18].iterrows(), start=16):
            payment_rows.append(
                {
                    "保单号": row["保单号"],
                    "赔案号": f"CASE{offset:03d}",
                    "实际赔付金额": Decimal(str(row["实际赔付金额"])) - Decimal("100.00"),
                    "案件状态": "成功",
                }
            )
        payment_rows.append(
            {
                "保单号": "CL9900998",
                "赔案号": "CASE998",
                "实际赔付金额": Decimal("66.00"),
                "案件状态": "成功",
            }
        )
        payment_rows.append(
            {
                "保单号": "CL9900999",
                "赔案号": "CASE999",
                "实际赔付金额": Decimal("88.00"),
                "案件状态": "成功",
            }
        )

        ledger_side = ledger.head(18).copy()
        ledger_side["赔案号"] = [f"CASE{i:03d}" for i in range(1, len(ledger_side) + 1)]
        ledger_side["案件状态"] = "已结案"
        payment = pd.DataFrame(payment_rows)

        detail, summary = crosscheck(ledger_side, payment)

        assert summary.matched_groups == 15
        assert summary.amount_diff_groups == 3
        assert summary.payment_only_groups == 2
        assert summary.ledger_only_groups == 0
        assert summary.identity_holds is True
        assert (
            summary.ledger_amount_total == summary.payment_amount_total + summary.diff_amount_total
        )
        assert len(detail) == 20

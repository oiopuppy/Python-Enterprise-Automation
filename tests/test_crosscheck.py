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

    def test_identity_catches_dropped_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """恒等式要能真的失败：分组漏掉一行时必须报不成立

        左边用逐行原始金额求和、右边用分组累计，两边不是同一个来源；
        改动前 diff_total 就是逐组差值累加，identity_gap 按构造恒为 0。
        """
        from insurance_audit.audit import crosscheck as module

        ledger = _ledger(
            [
                {"保单号": "CL9900001", "赔案号": "C1", "实际赔付金额": 100.00},
                {"保单号": "CL9900002", "赔案号": "C2", "实际赔付金额": 200.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900001", "赔案号": "C1", "实际赔付金额": 100.00}])

        original_group = module._group

        def _lossy_group(rows: object) -> object:
            grouped = original_group(rows)  # type: ignore[arg-type]
            for key in list(grouped):  # type: ignore[call-overload]
                if "CL9900002" in key:  # type: ignore[operator]
                    grouped.pop(key)  # type: ignore[attr-defined]
            return grouped

        monkeypatch.setattr(module, "_group", _lossy_group)

        _, summary = crosscheck(ledger, payment)

        assert summary.identity_holds is False
        assert summary.identity_gap == Decimal("200.00")


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
        # 三笔金额一模一样：等额分期或重复付款，都要人工看一眼，所以仍记疑点
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
        assert "台账重复记账嫌疑" in str(detail.iloc[0]["说明"])

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

    def test_reversed_status_mismatch_is_status_diff(self) -> None:
        """台账说退票、流水说已赔付 —— issue #32 要求「或反之」也算状态差"""
        ledger = _ledger(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "退票"}]
        )
        payment = _payment(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "已赔付",
                }
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_STATUS_DIFF
        assert row["状态一致"] == "否"
        assert summary.status_diff_groups == 1
        assert "台账退票" in str(row["说明"])

    def test_closed_ledger_with_pending_payment_is_status_diff(self) -> None:
        """台账说已结案、流水还在待支付/处理中 —— 最常见的状态差，也得报

        原实现只认「已结案 × 退票/失败」这两个极端相反的组合，流水写「待支付」
        「处理中」一律算「状态一致=是」，等于把最该看的漏掉了。
        """
        for pending in ("待支付", "处理中", "未支付", "在途"):
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
                [
                    {
                        "保单号": "CL9900100",
                        "赔案号": "C001",
                        "实际赔付金额": 400.00,
                        "案件状态": pending,
                    }
                ]
            )

            detail, summary = crosscheck(ledger, payment)

            row = detail.iloc[0]
            assert row["对账结果"] == RESULT_STATUS_DIFF, f"流水={pending} 应报状态差"
            assert row["状态一致"] == "否"
            assert summary.status_diff_groups == 1
            assert "还没付" in str(row["说明"])

    def test_pending_ledger_with_successful_payment_is_status_diff(self) -> None:
        """台账还挂着待支付、流水已经成功 —— 钱付了账上没销，也是状态差

        上面那条是「台账已结案 + 流水待支付」，这条是它的反向。只补单向的话，
        同一类错换个方向漏掉，等于把「对称」这两个字写在了注释里。
        """
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "待支付",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "成功"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_STATUS_DIFF
        assert row["状态一致"] == "否"
        assert summary.status_diff_groups == 1
        assert "未销账" in str(row["说明"])

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

    def test_missing_status_column_on_one_side_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """状态列只在一边有：检查静默关闭，必须留一条 warn

        否则报告里只有「—」，看起来像「查过了没问题」，实际一行都没比。
        """
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
        payment = pd.DataFrame([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00}])

        with caplog.at_level("WARNING"):
            detail, _ = crosscheck(ledger, payment)

        assert detail.iloc[0]["状态一致"] == "—"
        assert any("状态检查已关闭" in record.message for record in caplog.records)
        assert any("流水" in record.message for record in caplog.records)

    def test_single_side_rows_report_no_status_verdict(self) -> None:
        """只有一侧有行时谈不上「状态一致」，必须报 — 而不是「是」"""
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
        payment = _payment(
            [{"保单号": "CL9900999", "赔案号": "C999", "实际赔付金额": 700.00, "案件状态": "成功"}]
        )

        detail, _ = crosscheck(ledger, payment)

        by_result = {row["对账结果"]: row for _, row in detail.iterrows()}
        assert by_result[RESULT_LEDGER_ONLY]["状态一致"] == "—"
        assert by_result[RESULT_PAYMENT_ONLY]["状态一致"] == "—"

    def test_blank_status_on_one_side_reports_no_verdict(self) -> None:
        """状态列存在但一侧没填，就没法比，必须报 — 而不是「是」

        原实现只看「状态列在不在」，两侧都有行就直接 `not conflict` 判「是」，
        等于给了一份它给不出的保证。
        """
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
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": ""}]
        )

        detail, summary = crosscheck(ledger, payment)

        assert detail.iloc[0]["状态一致"] == "—", "流水状态是空的，不能说「一致」"
        assert summary.status_diff_groups == 0

    def test_both_sides_blank_status_reports_no_verdict(self) -> None:
        ledger = _ledger(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": ""}]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": ""}]
        )

        detail, _ = crosscheck(ledger, payment)

        assert detail.iloc[0]["状态一致"] == "—"
        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED

    def test_ledger_paid_word_counts_as_closed(self) -> None:
        """台账写「已支付」、流水写「退票」—— 也是钱没付出去账上结了

        原实现给台账、流水各存一份不对称的词表：台账侧没有「已支付/成功/
        支付成功」，流水侧没有「结案/赔付完成」。于是台账写「已支付」+ 流水写
        「退票」这种真状态差被静默算成「一致」（实测）。
        """
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "已支付",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "退票"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_STATUS_DIFF, "台账=已支付、流水=退票 是状态差"
        assert row["状态一致"] == "否"
        assert summary.status_diff_groups == 1
        assert "已支付" in str(row["说明"])

    def test_ledger_success_word_counts_as_closed(self) -> None:
        ledger = _ledger(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "成功"}]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "退票"}]
        )

        detail, _ = crosscheck(ledger, payment)

        assert detail.iloc[0]["对账结果"] == RESULT_STATUS_DIFF
        assert detail.iloc[0]["状态一致"] == "否"

    def test_payment_settled_word_counts_as_closed(self) -> None:
        """流水写「结案」、台账写「已结案」—— 两家写法不同，指同一件事，应算一致"""
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
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "结案"}]
        )

        detail, summary = crosscheck(ledger, payment)

        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED
        assert detail.iloc[0]["状态一致"] == "是"
        assert summary.status_diff_groups == 0

    def test_payment_settled_word_against_pending_ledger(self) -> None:
        """台账还挂着待支付、流水写「结案」—— 词表不对称时这条也会漏掉"""
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 400.00,
                    "案件状态": "待支付",
                }
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00, "案件状态": "结案"}]
        )

        detail, _ = crosscheck(ledger, payment)

        assert detail.iloc[0]["对账结果"] == RESULT_STATUS_DIFF
        assert "未销账" in str(detail.iloc[0]["说明"])

    def test_unknown_status_value_reports_no_verdict(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """状态写法收录不全（复核中/部分赔付…）时判不了，必须报 — 并说出来

        原实现把不在词表里的取值当成「不冲突」，于是「复核中」+「退票」、
        「异常」+「成功」全都报「状态一致=是」、既不告警也不进 issues ——
        报告看起来像查过了没问题。
        """
        for unknown in ("复核中", "部分赔付", "已核赔", "异常"):
            ledger = _ledger(
                [
                    {
                        "保单号": "CL9900100",
                        "赔案号": "C001",
                        "实际赔付金额": 400.00,
                        "案件状态": unknown,
                    }
                ]
            )
            payment = _payment(
                [
                    {
                        "保单号": "CL9900100",
                        "赔案号": "C001",
                        "实际赔付金额": 400.00,
                        "案件状态": "退票",
                    }
                ]
            )

            with caplog.at_level("WARNING"):
                detail, summary = crosscheck(ledger, payment)

            assert detail.iloc[0]["状态一致"] == "—", f"「{unknown}」归类不出来，不能说一致"
            assert summary.status_diff_groups == 0
        assert any("未收录的状态写法" in record.message for record in caplog.records)
        assert any("复核中" in record.message for record in caplog.records)

    def test_refund_then_repay_is_not_status_diff(self) -> None:
        """退票后重付：组里先退票、后已结案，最终付成了 —— 不算状态差

        原来用 ``any()`` 扫整组，扫到那条退票就把整组当 failed，正常的退票重付
        反被报成状态差（实测三种形态全中）。应当以组内最终状态为准。
        """
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 500.00,
                    "案件状态": "退票",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 500.00,
                    "案件状态": "已结案",
                },
            ]
        )
        payment = _payment(
            [{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1000.00, "案件状态": "成功"}]
        )

        detail, summary = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["对账结果"] == RESULT_MATCHED, "退票重付后最终付成，金额也相等"
        assert row["状态一致"] == "是"
        assert summary.status_diff_groups == 0

    def test_final_failed_after_success_is_status_diff(self) -> None:
        """反向：流水先成功后退票，最终是退票 —— 以最后一笔为准，这才是状态差"""
        ledger = _ledger(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 1000.00,
                    "案件状态": "已结案",
                }
            ]
        )
        payment = _payment(
            [
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 500.00,
                    "案件状态": "成功",
                },
                {
                    "保单号": "CL9900100",
                    "赔案号": "C001",
                    "实际赔付金额": 500.00,
                    "案件状态": "退票",
                },
            ]
        )

        detail, _ = crosscheck(ledger, payment)

        assert detail.iloc[0]["状态一致"] == "否"
        assert "退票" in str(detail.iloc[0]["说明"])


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

    def test_profile_single_key_is_respected(self) -> None:
        """profile 显式写 primary_key: ["保单号"] 必须生效，不能因为等于默认值被跳过"""
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C002", "实际赔付金额": 200.00},
            ]
        )
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        profile = MappingProfile(primary_key=("保单号",))

        detail, summary = crosscheck(ledger, payment, profile=profile)

        assert summary.key_fields == ["保单号"]
        assert len(detail) == 1, "同一保单的两个赔案要合成一组"
        assert detail.iloc[0]["台账笔数"] == 2

    def test_profile_without_primary_key_keeps_default_double_key(self) -> None:
        """只覆盖容差的 profile 不能顺手把主键降成单键

        ``MappingProfile.primary_key`` 默认是空元组表示「未配置」；若默认值写成
        ``("保单号",)``，任何 profile 都会被当成显式声明单键，同一保单的两个赔案
        就被合并成一组、金额也被加成 300 去比。
        """
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
        profile = MappingProfile(tolerance_absolute=Decimal("1"))

        detail, summary = crosscheck(ledger, payment, profile=profile)

        assert profile.primary_key == (), "默认必须是「未配置」"
        assert summary.key_fields == ["保单号", "赔案号"]
        assert len(detail) == 2
        assert summary.matched_groups == 2

    def test_missing_default_key_raises_instead_of_degrading(self) -> None:
        """缺一个默认键时直接报错，不能静默降级成单键把配置问题伪装成金额差"""
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = pd.DataFrame(
            {"保单号": ["CL9900100"], "实际赔付金额": [100.00], "案件状态": ["成功"]}
        )

        with pytest.raises(InvalidColumnError) as excinfo:
            crosscheck(ledger, payment)

        assert "赔案号" in str(excinfo.value)

    def test_missing_key_error_says_which_side(self) -> None:
        """缺列报错要说清是哪一侧缺，且列出那一侧实际的列

        实测过的错法：赔案号是流水缺的，消息里的「已识别的列」却是台账的列，
        照着消息排查会以为文件里已经有这一列了。
        """
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = pd.DataFrame(
            {"保单号": ["CL9900100"], "实际赔付金额": [100.00], "案件状态": ["成功"]}
        )

        with pytest.raises(InvalidColumnError) as excinfo:
            crosscheck(ledger, payment)

        message = str(excinfo.value)
        assert "流水数据文件缺少必要列" in message
        assert "赔案号" in message
        assert excinfo.value.details.get("side") == "流水"
        # 「已识别的列」必须是流水自己的列，不能拿台账的列顶替
        assert "赔案号" not in str(excinfo.value.details.get("identified_columns"))

    def test_profile_key_missing_column_raises(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        profile = MappingProfile(primary_key=("保单号", "报案日期"))

        with pytest.raises(InvalidColumnError) as excinfo:
            crosscheck(ledger, payment, profile=profile)

        assert "报案日期" in str(excinfo.value)

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


class TestRowNumbers:
    """行号口径：按 DataFrame 索引算，与单表对账的 idx + 2 一致"""

    def test_row_numbers_follow_dataframe_index(self) -> None:
        ledger = _ledger(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900101", "赔案号": "C002", "实际赔付金额": 100.00},
                {"保单号": "CL9900102", "赔案号": "C003", "实际赔付金额": 100.00},
            ]
        )
        ledger.index = [10, 11, 12]
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment.index = [50]

        detail, _ = crosscheck(ledger, payment)

        row = detail[detail["保单号"] == "CL9900100"].iloc[0]
        assert row["台账行号"] == "12", "索引 10 是第 12 行（表头占第 1 行）"
        assert row["流水行号"] == "52"

    def test_non_integer_index_falls_back_to_position(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])
        ledger.index = ["a"]
        payment = _payment([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00}])

        detail, _ = crosscheck(ledger, payment)

        assert detail.iloc[0]["台账行号"] == "2"


class TestKeyNormalization:
    """主键归一：数字与文本写法不同的同一个人要能对上"""

    def test_leading_zeros_and_text_numbers_match(self) -> None:
        ledger = _ledger([{"保单号": "012345", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = _payment([{"保单号": "12345", "赔案号": "C001", "实际赔付金额": 100.00}])

        detail, summary = crosscheck(ledger, payment)

        assert len(detail) == 1
        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED
        assert summary.ledger_only_groups == 0

    def test_float_nullable_key_column_matches_integer(self) -> None:
        """空值让整列变 Float64，键会写成 12345.0，必须还能对上 12345"""
        ledger = _ledger(
            [
                {"保单号": "12345", "赔案号": "C001", "实际赔付金额": 100.00, "案件状态": "已结案"},
                {"保单号": None, "赔案号": "C009", "实际赔付金额": 1.00, "案件状态": "已结案"},
            ]
        )
        ledger["保单号"] = ledger["保单号"].astype("Float64")
        payment = _payment([{"保单号": "12345", "赔案号": "C001", "实际赔付金额": 100.00}])

        detail, _ = crosscheck(ledger, payment)

        targets = detail[detail["赔案号"] == "C001"]
        assert len(targets) == 1
        assert targets.iloc[0]["对账结果"] == RESULT_MATCHED

    def test_long_numeric_key_keeps_precision(self) -> None:
        ledger = _ledger([{"保单号": 123456789012345678, "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = _payment(
            [{"保单号": "123456789012345678", "赔案号": "C001", "实际赔付金额": 100.00}]
        )

        detail, _ = crosscheck(ledger, payment)

        assert len(detail) == 1
        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED

    def test_text_number_with_decimal_point_matches_integer(self) -> None:
        """CSV 里常见的文本写法 "12345.0" 必须能和 12345 对上

        这是 Float64 空值列的另一种形态：整列被读成文本，键变成 "12345.0"，
        与流水的 "12345" 对不上，同一笔会被拆成两条孤岛。
        """
        ledger = _ledger([{"保单号": "12345.0", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = _payment([{"保单号": "12345", "赔案号": "C001", "实际赔付金额": 100.00}])

        detail, summary = crosscheck(ledger, payment)

        assert len(detail) == 1, "写法和数值都不同才该拆成两条"
        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED
        assert summary.ledger_only_groups == 0
        assert summary.payment_only_groups == 0

    def test_key_containing_separator_is_not_split(self) -> None:
        """键里含 " / " 时不能串到下一列"""
        ledger = _ledger([{"保单号": "P / 1", "赔案号": "C001", "实际赔付金额": 100.00}])
        payment = _payment([{"保单号": "P / 1", "赔案号": "C001", "实际赔付金额": 100.00}])

        detail, _ = crosscheck(ledger, payment)

        row = detail.iloc[0]
        assert row["保单号"] == "P / 1"
        assert row["赔案号"] == "C001"


class TestDuplicateKeySemantics:
    """同侧多行：不等额是正常分期，同额才是重复记账嫌疑"""

    def test_uneven_installments_are_not_flagged(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 900.00}])
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 200.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 300.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 400.00},
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        duplicates = [i for i in summary.issues if i["reason"] == ISSUE_DUPLICATE_KEY]
        assert duplicates == [], "分期金额各不相同，是正常形态，不该当疑点"
        assert detail.iloc[0]["对账结果"] == RESULT_MATCHED
        assert "流水分 3 笔支付" in str(detail.iloc[0]["说明"])

    def test_identical_amounts_are_flagged(self) -> None:
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 900.00}])
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 450.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 450.00},
            ]
        )

        detail, summary = crosscheck(ledger, payment)

        duplicates = [i for i in summary.issues if i["reason"] == ISSUE_DUPLICATE_KEY]
        assert len(duplicates) == 1
        assert duplicates[0]["side"] == "流水"
        assert "金额完全相同" in duplicates[0]["detail"]

    def test_duplicate_detail_names_the_repeated_amount(self) -> None:
        """组里只有一部分同额时，报的必须是重复那笔的金额与笔数

        实测过的错法：流水是 100 + 450 + 450，报成「出现 3 次、金额完全相同
        （100.00）」—— 笔数取成了整组行数、金额取成了第一行的金额，两个都不对。
        """
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1000.00}])
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 450.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 450.00},
            ]
        )

        _, summary = crosscheck(ledger, payment)

        duplicates = [i for i in summary.issues if i["reason"] == ISSUE_DUPLICATE_KEY]
        assert len(duplicates) == 1
        issue = duplicates[0]
        # 金额按数值比：源数据是 float 时 Decimal 会保留 ``450.0`` 这种写法，
        # 与报告里其他金额列口径一致，不在这里单独规范化
        assert Decimal(issue["amount"]) == Decimal("450.00"), "报的应该是重复那笔的金额"
        assert "其中 2 笔金额完全相同" in issue["detail"]
        assert "（450" in issue["detail"]
        assert "3 笔金额完全相同" not in issue["detail"], "整组 3 行并不都同额"

    def test_duplicate_issue_points_at_the_repeated_rows(self) -> None:
        """疑点里的行号要指向真正重复的那几行，不能指向整组第一行

        实测过的错法：流水是 100 + 450 + 450，行号报的是第 2 行（金额 100 那笔），
        照着这个行号去人工复核会核对到一笔完全无关的明细。
        """
        ledger = _ledger([{"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 1000.00}])
        payment = _payment(
            [
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 100.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 450.00},
                {"保单号": "CL9900100", "赔案号": "C001", "实际赔付金额": 450.00},
            ]
        )

        _, summary = crosscheck(ledger, payment)

        duplicates = [i for i in summary.issues if i["reason"] == ISSUE_DUPLICATE_KEY]
        assert len(duplicates) == 1
        issue = duplicates[0]
        assert issue["row"] == 3, "重复的两笔在第 3、4 行（表头占第 1 行）"
        assert issue["rows"] == [3, 4]


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

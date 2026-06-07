"""
测试配置与夹具 — Test Configuration & Fixtures

提供所有测试模块共用的 fixtures 和 mock 工具。
"""

from decimal import Decimal
from pathlib import Path
from typing import Generator

import pandas as pd
import pytest

from insurance_audit.models.claim import ClaimRecord


# =============================================================================
# 夹具：样本数据
# =============================================================================

@pytest.fixture
def sample_records() -> list[ClaimRecord]:
    """标准样本数据 — 用于大多数测试"""
    return [
        ClaimRecord(
            policy_id="CL9900100",
            customer_name="张三",
            claim_amount=Decimal("1000.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("400.00"),
        ),
        ClaimRecord(
            policy_id="CL9900101",
            customer_name="李四",
            claim_amount=Decimal("200.00"),
            deductible=Decimal("500.00"),
            payout_ratio=Decimal("0.80"),
            actual_payout=Decimal("0.00"),
        ),
        ClaimRecord(
            policy_id="CL9900102",
            customer_name="王五",
            claim_amount=Decimal("5000.00"),
            deductible=Decimal("800.00"),
            payout_ratio=Decimal("0.85"),
            actual_payout=Decimal("3570.00"),
        ),
    ]


@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    """样本 DataFrame — 用于对账等集成测试"""
    return pd.DataFrame({
        "保单号": ["CL9900100", "CL9900101", "CL9900102"],
        "客户姓名": ["张三", "李四", "王五"],
        "报案金额": [1000.0, 200.0, 5000.0],
        "免赔额": [500.0, 500.0, 800.0],
        "赔付比例": [0.80, 0.80, 0.85],
        "实际赔付金额": [400.0, 0.0, 3570.0],
    })


@pytest.fixture
def temp_excel_file(tmp_path: Path) -> Path:
    """临时 Excel 文件 — 用于文件读写测试"""
    df = pd.DataFrame({
        "保单号": ["CL9900100"],
        "客户姓名": ["测试用户"],
        "报案金额": [1000.0],
        "免赔额": [500.0],
        "赔付比例": [0.80],
        "实际赔付金额": [400.0],
    })
    path = tmp_path / "test_data.xlsx"
    df.to_excel(str(path), index=False)
    return path

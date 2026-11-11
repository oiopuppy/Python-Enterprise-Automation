"""表头别名映射与标准台账模板"""

from pathlib import Path

import pandas as pd
import pytest

from insurance_audit.core.validator import (
    REQUIRED_COLUMNS,
    normalize_columns,
    validate_columns,
)
from insurance_audit.utils.exceptions import InvalidColumnError

ROOT = Path(__file__).resolve().parents[1]


def test_alias_headers_are_normalized() -> None:
    """常见别名表头统一成标准列名"""
    df = pd.DataFrame(
        {
            "保单编号": ["CL1"],
            "客户名称": ["张三"],
            "赔款金额": [1000.0],
            "免赔": [0.0],
            "给付比例": [0.8],
            "实际赔付": [800.0],
        }
    )
    assert list(normalize_columns(df).columns) == list(REQUIRED_COLUMNS)


def test_headers_with_spaces_and_bom_are_cleaned() -> None:
    """BOM、全角空格、首尾空格不影响匹配"""
    df = pd.DataFrame(
        {
            "\ufeff保单号 ": ["CL1"],
            "客户姓名\u3000": ["张三"],
            "报案金额": [1000.0],
            "免赔额": [0.0],
            "赔付比例": [0.8],
            "实际赔付金额": [800.0],
        }
    )
    assert list(normalize_columns(df).columns) == list(REQUIRED_COLUMNS)


def test_missing_columns_message_is_actionable() -> None:
    """缺列报错同时列出已识别列与期望列名"""
    df = pd.DataFrame({"保单编号": ["CL1"], "备注": ["x"]})
    with pytest.raises(InvalidColumnError) as exc_info:
        validate_columns(df)

    message = str(exc_info.value)
    assert "缺少必要列" in message
    assert "已识别的列" in message
    assert "期望的列名" in message
    details = exc_info.value.details
    assert details["missing_columns"]
    assert "保单编号" in details["identified_columns"]


def test_template_matches_required_columns() -> None:
    """标准模板的表头必须与 REQUIRED_COLUMNS 一致"""
    template = ROOT / "data" / "templates" / "标准台账模板.xlsx"
    assert template.exists(), "缺少标准台账模板"
    assert list(pd.read_excel(template).columns) == list(REQUIRED_COLUMNS)

"""
性能 smoke — 防止单次审计回退到「分钟级」

1000 行是日常台账的典型下限；这里给 30 秒的宽裕预算，
只拦截数量级退化，不做精确基准（精确数字见 scripts/benchmark.py）。
"""

import time
from pathlib import Path

import pytest

from insurance_audit.core.engine import AuditEngine
from insurance_audit.data.generator import generate_mock_data

SMOKE_ROWS = 1000
BUDGET_SECONDS = 30.0


@pytest.mark.integration
def test_1000_rows_within_budget(tmp_path: Path) -> None:
    """1000 行端到端必须在预算内完成"""
    input_file = tmp_path / "mock.xlsx"
    generate_mock_data(
        num_records=SMOKE_ROWS,
        output_file=str(input_file),
        anomaly_ratio=0.1,
        seed=7,
    )

    started = time.perf_counter()
    summary = AuditEngine(
        input_file=str(input_file),
        output_file=str(tmp_path / "report.xlsx"),
    ).run()
    elapsed = time.perf_counter() - started

    assert summary.source_records == SMOKE_ROWS
    assert elapsed < BUDGET_SECONDS, f"1000 行耗时 {elapsed:.1f}s，疑似性能回退"

#!/usr/bin/env python
"""性能基准：在 1 万 / 10 万行语料上测端到端耗时与峰值内存。

数据由 ``generate_mock_data`` 按固定 seed 生成，报告与中间文件都放在临时目录，
因此重复运行的口径一致、不会污染仓库。

用法：
    python scripts/benchmark.py                 # 默认 1 万、10 万行
    python scripts/benchmark.py --rows 1000 10000
    python scripts/benchmark.py --rows 100000 --seed 42
"""

import argparse
import gc
import tempfile
import time
import tracemalloc
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

from insurance_audit.core.engine import AuditEngine
from insurance_audit.data.generator import generate_mock_data


def benchmark(rows: int, seed: int, workdir: Path) -> tuple[float, float, int]:
    """跑一轮审计，返回 (耗时秒, 峰值内存 MB, 实际读取行数)"""
    data_file = workdir / f"mock_{rows}.xlsx"
    report_file = workdir / f"report_{rows}.xlsx"
    if not data_file.exists():
        generate_mock_data(
            num_records=rows,
            output_file=str(data_file),
            anomaly_ratio=0.1,
            seed=seed,
        )

    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    summary = AuditEngine(input_file=str(data_file), output_file=str(report_file)).run()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / (1024 * 1024), summary.source_records


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="理赔审计性能基准")
    parser.add_argument(
        "--rows",
        nargs="+",
        type=int,
        default=[10000, 100000],
        help="要测的行数（默认 1 万、10 万）",
    )
    parser.add_argument("--seed", type=int, default=7, help="模拟数据随机种子")
    args = parser.parse_args(argv)

    print(f"{'行数':>10} | {'耗时(s)':>10} | {'峰值内存(MB)':>14}")
    print("-" * 42)
    with tempfile.TemporaryDirectory(prefix="insurance-benchmark-") as tmp:
        workdir = Path(tmp)
        for rows in args.rows:
            elapsed, peak, actual = benchmark(rows, args.seed, workdir)
            print(f"{actual:>10} | {elapsed:>10.2f} | {peak:>14.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

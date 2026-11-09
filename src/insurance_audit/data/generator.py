"""
模拟数据生成器 — Mock Data Generator

与原始版本的关键改进：
1. 不再重复计算逻辑，直接调用核心 calculator 模块；
2. 可显式指定输出路径，默认写到配置中的数据文件位置，
   避免「在哪个目录运行就生成到哪个目录」的路径分裂；
3. 默认注入少量对账差异（anomaly_ratio），让演示和集成测试
   能覆盖「发现异常」这条核心链路，而不是永远 100% 一致。
"""

import random
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from insurance_audit.core.calculator import calculate_payout
from insurance_audit.utils.config import settings
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# 注入差异时的单边偏移范围（元）
_MIN_ANOMALY_OFFSET = Decimal("3.00")
_MAX_ANOMALY_OFFSET = Decimal("20.00")


def generate_mock_data(
    num_records: int = 50,
    output_file: Optional[str] = None,
    anomaly_ratio: float = 0.1,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """
    生成模拟理赔数据

    Args:
        num_records: 模拟数据条数
        output_file: 输出文件路径；None 表示写到配置中的数据文件位置
        anomaly_ratio: 注入对账差异的记录占比（0~1），默认 0.1
        seed: 随机种子，便于测试复现

    Returns:
        生成的 DataFrame
    """
    if not 0 <= anomaly_ratio <= 1:
        raise ValueError(f"anomaly_ratio 必须在 0~1 之间: {anomaly_ratio}")

    target = Path(output_file) if output_file else settings.data.input_path
    target.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"开始生成 {num_records} 条模拟理赔数据...")

    rng = random.Random(seed)  # noqa: S311 — 模拟数据生成，不用于加密
    records = []
    anomaly_count = 0
    for i in range(num_records):
        # 生成随机数据
        policy_id = f"CL9900{i + 100:03d}"
        customer_name = f"客户{i + 1}"

        # 报案金额 100~5000 元
        claim_amount = Decimal(str(rng.randint(100, 5000)))
        # 免赔额 300~800 元
        deductible = Decimal(str(rng.randint(300, 800)))
        # 赔付比例 0.70~0.90
        ratio = Decimal(str(round(rng.uniform(0.70, 0.90), 2)))

        actual_payout = calculate_payout(
            claim_amount=claim_amount,
            deductible=deductible,
            ratio=ratio,
            policy_id=policy_id,
        )

        # 按比例注入人工录入误差，模拟真实对账中的异常记录
        if actual_payout > Decimal("0.00") and rng.random() < anomaly_ratio:
            offset = Decimal(
                str(round(rng.uniform(float(_MIN_ANOMALY_OFFSET), float(_MAX_ANOMALY_OFFSET)), 2))
            )
            sign = 1 if rng.random() < 0.5 else -1
            injected = actual_payout + sign * offset
            # 实际赔付不能为负、也不能超过报案金额（与模型校验保持一致）
            actual_payout = max(Decimal("0.00"), min(injected, claim_amount))
            anomaly_count += 1

        records.append(
            {
                "保单号": policy_id,
                "客户姓名": customer_name,
                "报案金额": float(claim_amount),
                "免赔额": float(deductible),
                "赔付比例": float(ratio),
                "实际赔付金额": float(actual_payout),
            }
        )

    df = pd.DataFrame(records)
    df.to_excel(target, index=False)

    logger.info(
        f"✅ 成功生成 {num_records} 条模拟理赔数据"
        f"（其中 {anomaly_count} 条注入了对账差异）: {target.absolute()}"
    )
    return df

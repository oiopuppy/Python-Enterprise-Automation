"""
模拟数据生成器 — Mock Data Generator

与原始版本的关键改进：不再重复计算逻辑
而是直接调用核心 calculator 模块生成模拟赔付数据，
确保 mock 数据与真实计算保持一致。
"""

import random
from decimal import Decimal
from pathlib import Path

import pandas as pd

from insurance_audit.core.calculator import calculate_payout
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)


def generate_mock_data(
    num_records: int = 50,
    output_file: str = "sample_claim_data.xlsx",
) -> pd.DataFrame:
    """
    生成模拟理赔数据
    
    改进：直接调用核心计算引擎生成赔付金额，
    保证 mock 数据行为和真实计算完全一致。
    
    Args:
        num_records: 模拟数据条数
        output_file: 输出文件名
    
    Returns:
        生成的 DataFrame
    """
    logger.info(f"开始生成 {num_records} 条模拟理赔数据...")

    records = []
    for i in range(num_records):
        # 生成随机数据
        policy_id = f"CL9900{i + 100:03d}"
        customer_name = f"客户{i + 1}"
        
        # 报案金额 100~5000 元
        claim_amount = Decimal(str(random.randint(100, 5000)))
        # 免赔额 300~800 元
        deductible = Decimal(str(random.randint(300, 800)))
        # 赔付比例 0.70~0.90
        ratio = Decimal(str(round(random.uniform(0.70, 0.90), 2)))
        
        # ===== 关键改进：调用真正的计算引擎 =====
        actual_payout = calculate_payout(
            claim_amount=claim_amount,
            deductible=deductible,
            ratio=ratio,
            policy_id=policy_id,
        )

        records.append({
            "保单号": policy_id,
            "客户姓名": customer_name,
            "报案金额": float(claim_amount),
            "免赔额": float(deductible),
            "赔付比例": float(ratio),
            "实际赔付金额": float(actual_payout),
        })

    df = pd.DataFrame(records)

    # 保存到文件
    df.to_excel(output_file, index=False)
    
    path = Path(output_file).absolute()
    logger.info(f"✅ 成功生成 {num_records} 条模拟理赔数据: {path}")
    return df

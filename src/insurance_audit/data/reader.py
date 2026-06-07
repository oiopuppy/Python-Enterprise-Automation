"""
数据读取层 — Data Reader

支持：
1. Excel文件读取
2. 数据完整性校验
3. 多种文件格式支持（可扩展）
"""

from pathlib import Path

import pandas as pd

from insurance_audit.utils.exceptions import FileNotFoundError, IOFailure
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)


def read_excel(file_path: str | Path) -> pd.DataFrame:
    """
    读取Excel数据文件
    
    Args:
        file_path: Excel文件路径
    
    Returns:
        数据的 DataFrame
    
    Raises:
        FileNotFoundError: 文件不存在
        IOFailure: 读取失败
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(str(path.absolute()))
    
    if not path.suffix.lower() in (".xlsx", ".xls"):
        logger.warning(f"文件扩展名非标准Excel格式: {path.suffix}")

    try:
        logger.info(f"正在读取数据文件: {path.name}")
        df = pd.read_excel(
            str(path.absolute()),
            dtype_backend="numpy_nullable",
        )
        logger.info(
            f"读取成功: {len(df)} 行 x {len(df.columns)} 列"
        )
        logger.debug(f"列名: {list(df.columns)}")
        return df
    except Exception as e:
        raise IOFailure(
            operation="read_excel",
            path=str(path.absolute()),
            original_error=str(e),
        )

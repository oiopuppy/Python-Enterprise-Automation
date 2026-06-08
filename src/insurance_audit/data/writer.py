"""
数据写入层 — Data Writer

支持：
1. Excel报告输出
2. 审计结果格式化
3. 输出文件路径管理
"""

from pathlib import Path
from typing import Union

import pandas as pd

from insurance_audit.utils.exceptions import IOFailure
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)


def write_excel(
    df: pd.DataFrame,
    output_path: Union[str, Path],
    sheet_name: str = "审计结果",
) -> Path:
    """
    将DataFrame写入Excel文件
    
    Args:
        df: 要写入的数据
        output_path: 输出路径
        sheet_name: Sheet名称
    
    Returns:
        输出文件的绝对路径
    
    Raises:
        IOFailure: 写入失败
    """
    path = Path(output_path)
    
    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        logger.info(f"正在写入报告: {path.name}")
        
        # 使用 openpyxl 引擎（支持 xlsx 格式）
        with pd.ExcelWriter(
            str(path.absolute()),
            engine="openpyxl",
        ) as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)

            # 自动调整列宽
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = max(
                    len(str(cell.value or "")) for cell in column
                )
                adjusted_width = min(max_length + 4, 50)
                worksheet.column_dimensions[
                    column[0].column_letter
                ].width = adjusted_width

        abs_path = path.absolute()
        size_kb = path.stat().st_size / 1024
        logger.info(
            f"报告已保存: {abs_path} ({size_kb:.1f} KB)"
        )
        return abs_path

    except Exception as e:
        raise IOFailure(
            operation="write_excel",
            path=str(path.absolute()),
            original_error=str(e),
        )

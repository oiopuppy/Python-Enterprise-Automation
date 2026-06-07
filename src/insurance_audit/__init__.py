"""
保险理赔数据自动化审计系统
China Life Insurance Claim Data Automated Audit System

企业级版本 2.0.0
Enterprise Edition 2.0.0

本系统提供：
1. 保险理赔数据的自动化对账与审计
2. 业务规则驱动的赔付金额核算
3. 全链路审计追溯与报告生成
4. 支持央企合规要求的数据完整性保障
"""

__version__ = "2.0.0"
__app_name__ = "保险理赔审计系统"
__description__ = "Enterprise-grade insurance claim data audit automation system"
__author__ = "Senior Developer Team"

from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)
logger.info(f"{__app_name__} v{__version__} loaded — 企业级审计引擎就绪")

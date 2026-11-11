"""
审计留痕清单 — 输入指纹、工具版本与生效配置

用途：
1. 证明「审的是哪份文件」：SHA256 + 字节数 + 行数；
2. 证明「用的是什么版本与参数」：工具版本、Python 版本、关键业务配置；
3. 同一输入两次运行，清单除生成时间外完全一致，便于归档与复核。

不记录任何密钥：这里只读取业务配置（免赔额、比例、容差相关的十进制位数等），
不触碰 ``.env`` 中的账号、令牌类变量。
"""

import hashlib
import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from insurance_audit import __version__
from insurance_audit.utils.config import settings
from insurance_audit.utils.exceptions import IOFailure
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024


def file_fingerprint(path: Union[str, Path]) -> dict[str, Any]:
    """计算文件的 SHA256 与字节数（审计留痕的证据字段）"""
    file_path = Path(path)
    digest = hashlib.sha256()
    total = 0
    try:
        with file_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
                digest.update(chunk)
                total += len(chunk)
    except OSError as e:
        raise IOFailure(
            operation="fingerprint",
            path=str(file_path),
            original_error=str(e),
        ) from e
    return {"path": str(file_path), "bytes": total, "sha256": digest.hexdigest()}


def build_manifest(
    input_path: Union[str, Path],
    rows: int,
    output_path: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    """构造审计清单（不含生成时间以外的运行时信息）"""
    insurance = settings.insurance
    manifest: dict[str, Any] = {
        "tool_version": __version__,
        "python_version": platform.python_version(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input": {**file_fingerprint(input_path), "rows": rows},
        "config": {
            "default_deductible": str(insurance.default_deductible),
            "default_ratio": str(insurance.default_ratio),
            "decimal_places": insurance.decimal_places,
            "policy_prefix": insurance.policy_prefix,
            "min_claim_amount": str(insurance.min_claim_amount),
            "max_claim_amount": str(insurance.max_claim_amount),
        },
    }
    if output_path is not None:
        manifest["output"] = {"path": str(output_path)}
    return manifest


def write_manifest(manifest: dict[str, Any], output_path: Union[str, Path]) -> Path:
    """把审计清单写入 JSON 文件（``--manifest``）"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    abs_path = path.absolute()
    logger.info(f"审计清单已生成: {abs_path}")
    return abs_path

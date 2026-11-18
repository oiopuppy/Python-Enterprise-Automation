"""
数据读取层 — Data Reader

目标：让客户的原始表不用改就能跑。支持：

1. Excel（.xlsx / .xls / .xlsm），可选择 sheet
2. CSV（自动探测 GBK / UTF-8 编码与分隔符）
3. 表头之前的说明行（skiprows）
4. 按映射 profile 把客户原始列名整形成标准字段
5. 金额单位换算（万元 → 元）与日期格式归一

命令行（模板 / profile 初始化 / 查看文件结构）：

    python -m insurance_audit.data.reader --print-template --out 模板.xlsx
    python -m insurance_audit.data.reader --init-profile profiles/customer-a.json
    python -m insurance_audit.data.reader --inspect 客户台账.csv
"""

import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from insurance_audit.utils.config import STANDARD_FIELDS, MappingProfile, load_profile
from insurance_audit.utils.exceptions import FileNotFoundError, IOFailure
from insurance_audit.utils.logger import get_logger

logger = get_logger(__name__)

# Excel 家族与纯文本家族
EXCEL_SUFFIXES = (".xlsx", ".xls", ".xlsm")
CSV_SUFFIXES = (".csv", ".tsv", ".txt")

# CSV 编码候选：utf-8-sig 能吃掉 BOM，gb18030 是 GBK/GB2312 的超集
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030")

# 内置默认 profile 的 6 个核心字段（与 validator.REQUIRED_COLUMNS 同序）
CORE_FIELDS = STANDARD_FIELDS[:6]

# 参与金额换算与日期归一的字段
MONEY_FIELDS = ("报案金额", "免赔额", "实际赔付金额", "保额")
DATE_FIELDS = ("报案日期", "受理日期", "核定日期", "支付日期")

# 万元换算用的乘数（用 Decimal 算，避免 0.1 * 10000 的浮点尾巴）
WAN_FACTOR = Decimal("10000")


def _decode_head(path: Path, size: int = 65536) -> tuple[str, str]:
    """读取文件开头若干字节，判断编码

    Returns:
        (编码名, 文本片段)

    Raises:
        IOFailure: 所有候选编码都解不开
    """
    raw = path.read_bytes()[:size]
    errors = []
    for encoding in ENCODING_CANDIDATES:
        try:
            return encoding, raw.decode(encoding)
        except UnicodeDecodeError as e:
            errors.append(f"{encoding}: {e.reason}")
    raise IOFailure(
        operation="read_table",
        path=str(path.absolute()),
        original_error=(
            "无法确定文件编码，请用 profile 的 encoding 字段指定（支持 UTF-8 / GBK / GB18030）"
            f"；尝试结果: {'; '.join(errors)}"
        ),
    )


def detect_encoding(path: Union[str, Path]) -> str:
    """探测文本文件的编码（UTF-8 优先，其次 GB18030）"""
    encoding, _ = _decode_head(Path(path))
    return encoding


def _sniff_delimiter(sample: str) -> str:
    """从样本里猜分隔符，猜不出来就用逗号"""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def list_sheets(file_path: Union[str, Path]) -> list[str]:
    """列出 Excel 的所有 sheet 名（CSV 返回空列表）"""
    path = Path(file_path)
    if path.suffix.lower() not in EXCEL_SUFFIXES:
        return []
    try:
        with pd.ExcelFile(str(path.absolute())) as book:
            return [str(name) for name in book.sheet_names]
    except Exception as e:
        raise IOFailure(
            operation="list_sheets",
            path=str(path.absolute()),
            original_error=str(e),
        ) from e


def _read_excel_frame(
    path: Path,
    sheet: Optional[Union[str, int]],
    skiprows: int,
) -> pd.DataFrame:
    """读 Excel；sheet 不存在时报出可选 sheet"""
    try:
        with pd.ExcelFile(str(path.absolute())) as book:
            available = [str(name) for name in book.sheet_names]
            if sheet is None:
                target: Union[str, int] = 0
            elif isinstance(sheet, int):
                target = sheet
            else:
                if sheet not in available:
                    raise IOFailure(
                        operation="read_table",
                        path=str(path.absolute()),
                        original_error=(f"sheet 不存在: {sheet!r}；文件里的 sheet: {available}"),
                    )
                target = sheet
            return pd.read_excel(
                book,
                sheet_name=target,
                skiprows=skiprows,
                dtype_backend="numpy_nullable",
            )
    except IOFailure:
        raise
    except Exception as e:
        raise IOFailure(
            operation="read_table",
            path=str(path.absolute()),
            original_error=str(e),
        ) from e


def _read_csv_frame(
    path: Path,
    encoding: Optional[str],
    skiprows: int,
) -> tuple[pd.DataFrame, str]:
    """读 CSV，返回 (DataFrame, 实际使用的编码)"""
    if encoding and encoding.lower() != "auto":
        try:
            text = path.read_bytes().decode(encoding)
        except UnicodeDecodeError as e:
            raise IOFailure(
                operation="read_table",
                path=str(path.absolute()),
                original_error=f"用编码 {encoding} 读取失败: {e.reason}",
            ) from e
        resolved = encoding
    else:
        resolved, text = _decode_head(path)

    delimiter = _sniff_delimiter("\n".join(text.splitlines()[:20]))
    try:
        df = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            skiprows=skiprows,
            dtype_backend="numpy_nullable",
            skip_blank_lines=True,
        )
    except Exception as e:
        raise IOFailure(
            operation="read_table",
            path=str(path.absolute()),
            original_error=str(e),
        ) from e
    return df, resolved


def _apply_profile(
    df: pd.DataFrame,
    profile: MappingProfile,
    path: Path,
    source_label: str,
) -> pd.DataFrame:
    """按 profile 把源列名换成标准字段，并做单位/日期归一"""
    if profile.columns:
        source_map = profile.column_map
        header_line = profile.skiprows + 1
        missing = [
            (field_name, source)
            for source, field_name in source_map.items()
            if source not in df.columns and field_name not in df.columns
        ]
        if missing:
            detail = "、".join(f"{source!r}（标准字段 {field}）" for field, source in missing)
            raise IOFailure(
                operation="apply_profile",
                path=str(path.absolute()),
                original_error=(
                    f"profile 声明的列在 {source_label} 里找不到: {detail}；"
                    f"表头位于第 {header_line} 行；文件实际列名: {list(df.columns)}"
                ),
            )
        rename = {source: field for source, field in source_map.items() if source in df.columns}
        if rename:
            df = df.rename(columns=rename)
            logger.info(f"已按 profile 映射列名: {rename}")
    if profile.amount_unit == "wan":
        df = _convert_amount_unit(df)
    df = _normalize_dates(df, profile)
    return df


def _convert_amount_unit(df: pd.DataFrame) -> pd.DataFrame:
    """万元 → 元（只动出现的金额列）"""

    def _scale(value: Any) -> Any:
        if pd.isna(value):
            return value
        try:
            return (Decimal(str(value)) * WAN_FACTOR).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return value

    for column in MONEY_FIELDS:
        if column in df.columns:
            df[column] = df[column].map(_scale)
    logger.info("已按 profile 把金额单位从万元换算为元")
    return df


def _normalize_dates(df: pd.DataFrame, profile: MappingProfile) -> pd.DataFrame:
    """把日期列统一成 YYYY-MM-DD 字符串，解析不了的保持原值"""
    columns = [name for name in DATE_FIELDS if name in df.columns]
    if profile.timeline:
        columns = sorted(set(columns) | {name for name in profile.timeline if name in df.columns})
    for column in columns:
        df[column] = df[column].map(lambda value: _parse_date(value, profile.date_formats))
    return df


def _parse_date(value: Any, formats: Sequence[str]) -> Any:
    """按 profile 的格式顺序解析日期，失败则原样返回"""
    if pd.isna(value):
        return value
    for fmt in formats:
        try:
            return pd.to_datetime(str(value).strip(), format=fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    return value


def read_table(
    file_path: Union[str, Path],
    sheet: Optional[Union[str, int]] = None,
    encoding: Optional[str] = None,
    skiprows: Optional[int] = None,
    profile: Optional[Union[str, Path, MappingProfile]] = None,
) -> pd.DataFrame:
    """读取台账（Excel 或 CSV），并按 profile 整形成标准列

    Args:
        file_path: 文件路径
        sheet: Excel 的 sheet 名或序号；默认取 profile.sheet，再默认第一个
        encoding: CSV 编码；默认取 profile.encoding，再自动探测
        skiprows: 表头之前跳过的行数；默认取 profile.skiprows
        profile: 映射 profile（文件路径 / MappingProfile / None=环境变量 DATA_PROFILE）

    Returns:
        已按 profile 重命名、单位与日期归一后的 DataFrame

    Raises:
        FileNotFoundError: 文件不存在
        IOFailure: 读取失败、sheet 不存在、profile 声明的列找不到
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(str(path.absolute()))

    active = load_profile(profile)
    if sheet is None:
        sheet = active.sheet
    if encoding is None:
        encoding = active.encoding
    if skiprows is None:
        skiprows = active.skiprows

    suffix = path.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        if suffix == ".xls":
            try:
                import xlrd  # noqa: F401
            except ImportError as e:
                raise IOFailure(
                    operation="read_excel",
                    path=str(path.absolute()),
                    original_error=(
                        "读取 .xls 需要 xlrd：pip install xlrd，或把文件另存为 .xlsx 后重试"
                    ),
                ) from e
        logger.info(f"正在读取数据文件: {path.name}")
        df = _read_excel_frame(path, sheet, skiprows)
        label = f"文件 {path.name}" + (f" 的 sheet {sheet!r}" if sheet is not None else "")
    elif suffix in CSV_SUFFIXES:
        logger.info(f"正在读取数据文件: {path.name}")
        df, resolved = _read_csv_frame(path, encoding, skiprows)
        logger.info(f"CSV 编码: {resolved}")
        label = f"文件 {path.name}"
    else:
        raise IOFailure(
            operation="read_table",
            path=str(path.absolute()),
            original_error=(
                f"不支持的文件类型: {suffix or '(无扩展名)'}；支持 {list(EXCEL_SUFFIXES + CSV_SUFFIXES)}"
                "；请把文件另存为 .xlsx 或 .csv 后重试"
            ),
        )

    logger.info(f"读取成功: {len(df)} 行 x {len(df.columns)} 列")
    logger.debug(f"列名: {list(df.columns)}")
    return _apply_profile(df, active, path, label)


def read_excel(file_path: Union[str, Path], **kwargs: Any) -> pd.DataFrame:
    """兼容旧调用：读取数据文件（现在同时支持 Excel 与 CSV）"""
    return read_table(file_path, **kwargs)


def build_template(profile: Optional[Union[str, Path, MappingProfile]] = None) -> pd.DataFrame:
    """生成标准台账模板（只有表头，可直接填数）

    Args:
        profile: 指定时按 profile 声明的源列名输出（方便客户沿用原有表头）

    Returns:
        空 DataFrame
    """
    active = load_profile(profile)
    columns = list(active.columns.values()) if active.columns else list(CORE_FIELDS)
    return pd.DataFrame(columns=columns)


def write_template(
    output_path: Union[str, Path],
    profile: Optional[Union[str, Path, MappingProfile]] = None,
    full: bool = False,
) -> Path:
    """把标准模板写到文件（.xlsx 或 .csv）

    Args:
        output_path: 输出路径，扩展名决定格式
        profile: 指定时按 profile 声明的源列名输出
        full: 是否加上 9 个可选的 v2 扩展字段（赔案号、时间轴等）
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    active = load_profile(profile)
    if active.columns:
        columns = list(active.columns.values())
    elif full:
        columns = list(STANDARD_FIELDS)
    else:
        columns = list(CORE_FIELDS)
    frame = pd.DataFrame(columns=columns)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        frame.to_excel(path, index=False)
    logger.info(f"模板已生成: {path}（{len(columns)} 列）")
    return path


def init_profile(
    output_path: Union[str, Path],
    file_path: Optional[Union[str, Path]] = None,
    skiprows: int = 0,
) -> Path:
    """生成一份 profile 草稿

    Args:
        output_path: profile 输出路径（JSON）
        file_path: 给了就按该文件的实际列名预填，否则用标准列名
        skiprows: 表头之前要跳过的说明行数（预填时用）
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if file_path is not None:
        source = Path(file_path)
        profile = MappingProfile()
        if source.suffix.lower() in CSV_SUFFIXES:
            encoding, text = _decode_head(source)
            delimiter = _sniff_delimiter("\n".join(text.splitlines()[:20]))
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            header = rows[skiprows] if len(rows) > skiprows else []
            profile = MappingProfile(
                encoding=encoding, skiprows=skiprows, columns=_guess_columns(header)
            )
        else:
            header = [
                str(name)
                for name in pd.read_excel(
                    str(source.absolute()), nrows=0, skiprows=skiprows
                ).columns
            ]
            profile = MappingProfile(skiprows=skiprows, columns=_guess_columns(header))
    else:
        profile = MappingProfile()

    payload: dict[str, Any] = {
        "role": profile.role,
        "columns": profile.columns,
        "primary_key": list(profile.primary_key),
        "timeline": list(profile.timeline),
        "date_formats": list(profile.date_formats),
        "amount_unit": profile.amount_unit,
        "skiprows": profile.skiprows,
    }
    if profile.sheet:
        payload["sheet"] = profile.sheet
    if profile.encoding:
        payload["encoding"] = profile.encoding
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info(f"profile 草稿已生成: {path}")
    return path


# 常见英文列名提示：客户导出的系统表多半是英文表头，用于预填 profile 草稿
ENGLISH_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "保单号": ("policy_id", "policy_no", "policy_number", "policyno"),
    "客户姓名": ("customer_name", "insured_name", "name", "holder_name"),
    "报案金额": ("claim_amount", "claim_amt", "report_amount", "amount"),
    "免赔额": ("deductible", "franchise", "deductible_amount"),
    "赔付比例": ("payout_ratio", "ratio", "pay_ratio", "rate"),
    "实际赔付金额": ("actual_payout", "paid_amount", "payment", "actual_amount"),
    "赔案号": ("case_no", "claim_no", "case_id"),
    "被保险人": ("insured_name", "insured"),
    "保额": ("policy_limit", "sum_insured", "limit"),
    "案件状态": ("status", "case_status"),
    "收款账号哈希": ("bank_account_hash", "account_hash"),
    "报案日期": ("report_date", "report_dt"),
    "受理日期": ("accept_date", "accepted_date"),
    "核定日期": ("verify_date", "verified_date"),
    "支付日期": ("pay_date", "payment_date"),
}


def _guess_columns(header: Sequence[str]) -> dict[str, str]:
    """按标准字段名、中文别名与常见英文名粗匹配，能对上的预填进 profile"""
    from insurance_audit.core.validator import COLUMN_ALIASES  # 避免循环导入

    cleaned = {str(name).strip(): str(name) for name in header}
    lowered = {str(name).strip().lower(): str(name) for name in header}
    mapping: dict[str, str] = {}
    for field_name in CORE_FIELDS:
        if field_name in cleaned:
            mapping[field_name] = cleaned[field_name]
            continue
        alias_hit = next(
            (alias for alias in COLUMN_ALIASES.get(field_name, ()) if alias in cleaned), None
        )
        if alias_hit is not None:
            mapping[field_name] = cleaned[alias_hit]
            continue
        english_hit = next(
            (lowered[hint] for hint in ENGLISH_FIELD_HINTS.get(field_name, ()) if hint in lowered),
            None,
        )
        if english_hit is not None:
            mapping[field_name] = english_hit
    return mapping


def inspect_file(file_path: Union[str, Path], skiprows: int = 0) -> dict[str, Any]:
    """看一个文件的真实结构：sheet、编码、列名、行数（排障用）

    Args:
        file_path: 文件路径
        skiprows: 表头之前跳过的说明行数（与 profile 一致时看到的就是真实表头）
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(str(path.absolute()))
    info: dict[str, Any] = {"path": str(path.absolute()), "suffix": path.suffix.lower()}
    if path.suffix.lower() in EXCEL_SUFFIXES:
        sheets = list_sheets(path)
        info["sheets"] = sheets
        frame = pd.read_excel(
            str(path.absolute()), sheet_name=0, skiprows=skiprows, dtype_backend="numpy_nullable"
        )
        info["columns"] = [str(name) for name in frame.columns]
        info["rows"] = int(len(frame))
    elif path.suffix.lower() in CSV_SUFFIXES:
        encoding, text = _decode_head(path)
        delimiter = _sniff_delimiter("\n".join(text.splitlines()[:20]))
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        body = rows[skiprows:]
        info["encoding"] = encoding
        info["delimiter"] = delimiter
        info["columns"] = body[0] if body else []
        info["rows"] = max(len(body) - 1, 0)
    else:
        raise IOFailure(
            operation="inspect",
            path=str(path.absolute()),
            original_error=f"不支持的文件类型: {path.suffix or '(无扩展名)'}",
        )
    return info


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口：模板生成 / profile 初始化 / 文件结构查看"""
    parser = argparse.ArgumentParser(
        prog="python -m insurance_audit.data.reader",
        description="读取层工具：生成标准模板、初始化映射 profile、查看文件结构",
    )
    parser.add_argument(
        "--print-template",
        "--make-template",
        dest="print_template",
        action="store_true",
        help="生成标准台账模板（默认 xlsx）",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="模板包含 9 个可选的 v2 扩展字段（赔案号、时间轴等）",
    )
    parser.add_argument(
        "--format",
        choices=["xlsx", "csv"],
        default="xlsx",
        help="模板格式（默认 xlsx）",
    )
    parser.add_argument("--out", help="输出路径")
    parser.add_argument(
        "--init-profile",
        metavar="PATH",
        nargs="?",
        const="profiles/profile.json",
        help="生成 profile 草稿（可指定输出路径）",
    )
    parser.add_argument("--from", dest="source", help="配合 --init-profile：按该文件的表头预填")
    parser.add_argument(
        "--skiprows",
        type=int,
        default=0,
        help="表头之前跳过的说明行数（--init-profile / --inspect 用）",
    )
    parser.add_argument("--profile", help="映射 profile 文件（默认读环境变量 DATA_PROFILE）")
    parser.add_argument("--inspect", metavar="FILE", help="查看文件的 sheet / 编码 / 列名")
    args = parser.parse_args(argv)

    try:
        if args.print_template:
            output = args.out or f"标准台账模板.{args.format}"
            path = write_template(output, profile=args.profile, full=args.full)
            print(f"模板已生成: {path}")
            print(f"列: {list(pd.read_excel(str(path)).columns) if path.suffix == '.xlsx' else ''}")
            return 0
        if args.init_profile:
            path = init_profile(args.init_profile, file_path=args.source, skiprows=args.skiprows)
            print(f"profile 草稿已生成: {path}")
            print(path.read_text(encoding="utf-8"))
            return 0
        if args.inspect:
            info = inspect_file(args.inspect, skiprows=args.skiprows)
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
    except Exception as e:
        print(f"失败: {e}", file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""
校验 .env.example 覆盖了代码读取的全部环境变量。

用法：
    python scripts/check_env_example.py

被注释掉的变量（例如 ``# PROJECT_ROOT=/app``）算作已声明，因为它们是给使用者的提示。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_FILES = [
    ROOT / "src" / "insurance_audit" / "utils" / "config.py",
    ROOT / "src" / "insurance_audit" / "utils" / "logger.py",
]

DECLARED_PATTERN = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)
READER_PATTERN = re.compile(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"')


def declared_keys(path: Path) -> set[str]:
    """读取模板里声明的变量名（含注释掉的行）。"""
    return set(DECLARED_PATTERN.findall(path.read_text(encoding="utf-8")))


def read_keys(paths: list[Path]) -> set[str]:
    """读取代码中通过 os.getenv 使用的变量名。"""
    keys: set[str] = set()
    for path in paths:
        if path.exists():
            keys.update(READER_PATTERN.findall(path.read_text(encoding="utf-8")))
    return keys


def main() -> int:
    declared = declared_keys(ENV_EXAMPLE)
    used = read_keys(CONFIG_FILES)
    missing = sorted(used - declared)
    extra = sorted(declared - used)

    for key in extra:
        print(f"  [提示] .env.example 中的 {key} 当前没有被代码读取")
    if missing:
        print(f"发现 {len(missing)} 个配置项未写入 .env.example：")
        for key in missing:
            print(f"  - {key}")
        return 1
    print(f"环境变量模板检查通过（{len(used)} 个变量）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

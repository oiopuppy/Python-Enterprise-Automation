"""
校验版本号在 pyproject.toml、包 __init__ 与 CHANGELOG 中一致。

用法：
    python scripts/check_version_consistency.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "insurance_audit" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"

VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
INIT_PATTERN = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
RELEASE_PATTERN = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def extract(pattern: re.Pattern[str], path: Path, label: str) -> str:
    """从文件中提取第一个匹配到的版本号。"""
    match = pattern.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"无法从 {label} 中解析出版本号")
    return match.group(1)


def find_problems(root: Path) -> list[str]:
    """返回版本号不一致的问题列表（空列表表示通过）。"""
    pyproject_version = extract(VERSION_PATTERN, root / "pyproject.toml", "pyproject.toml")
    init_version = extract(
        INIT_PATTERN, root / "src" / "insurance_audit" / "__init__.py", "__init__.py"
    )
    releases = RELEASE_PATTERN.findall((root / "CHANGELOG.md").read_text(encoding="utf-8"))

    problems: list[str] = []
    if init_version != pyproject_version:
        problems.append(f"__init__.py={init_version} 与 pyproject.toml={pyproject_version} 不一致")
    if pyproject_version not in releases:
        problems.append(f"CHANGELOG.md 缺少 {pyproject_version} 的条目")
    return problems


def main() -> int:
    problems = find_problems(ROOT)
    if problems:
        print("版本号一致性检查未通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    version = extract(VERSION_PATTERN, PYPROJECT, "pyproject.toml")
    print(f"版本号一致性检查通过（{version}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

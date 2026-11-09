"""
检查 Markdown 文档中的相对链接是否指向真实文件。

用法：
    python scripts/check_markdown_links.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE = "```"


def iter_markdown_files(root: Path) -> list[Path]:
    """返回需要检查的 Markdown 文件（排除构建产物与缓存目录）。"""
    files: list[Path] = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        files.append(path)
    return sorted(files)


def strip_code_fences(text: str) -> str:
    """去掉围栏代码块：里面的链接是示例，不应参与检查。"""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.strip().startswith(FENCE):
            inside = not inside
            continue
        if not inside:
            kept.append(line)
    return "\n".join(kept)


def is_external(target: str) -> bool:
    """站外链接、页内锚点、邮件与电话链接不检查。"""
    return target.startswith(("#", "http://", "https://", "mailto:", "tel:"))


def find_broken_links(root: Path) -> list[str]:
    """返回形如 ``文件 -> 链接`` 的失效项。"""
    broken: list[str] = []
    for md in iter_markdown_files(root):
        text = strip_code_fences(md.read_text(encoding="utf-8"))
        for match in LINK_PATTERN.finditer(text):
            target = match.group(1).strip()
            if not target or is_external(target):
                continue
            # 去掉锚点与查询串后再判断文件是否存在
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            resolved = (md.parent / path_part).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(root).as_posix()} -> {target}")
    return broken


def main() -> int:
    broken = find_broken_links(ROOT)
    if broken:
        print(f"发现 {len(broken)} 个失效的 Markdown 相对链接：")
        for item in broken:
            print(f"  - {item}")
        return 1
    total = len(iter_markdown_files(ROOT))
    print(f"Markdown 链接检查通过（{total} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

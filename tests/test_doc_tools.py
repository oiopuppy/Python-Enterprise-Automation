"""文档检查脚本的负向测试：每条规则都要能真的抓到问题。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name: str) -> ModuleType:
    """按文件路径加载 scripts 下的脚本（scripts 不是包）。"""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_markdown_links_detect_missing_file(tmp_path: Path) -> None:
    module = load_module("check_markdown_links")
    (tmp_path / "README.md").write_text("[缺失](missing.md)\n", encoding="utf-8")
    assert module.find_broken_links(tmp_path) == ["README.md -> missing.md"]


def test_markdown_links_accept_existing_and_external(tmp_path: Path) -> None:
    module = load_module("check_markdown_links")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[ok](docs/a.md)\n[web](https://example.com)\n[anchor](#top)\n",
        encoding="utf-8",
    )
    assert module.find_broken_links(tmp_path) == []


def test_markdown_links_ignore_code_fence(tmp_path: Path) -> None:
    module = load_module("check_markdown_links")
    (tmp_path / "README.md").write_text("```\n[x](missing.md)\n```\n", encoding="utf-8")
    assert module.find_broken_links(tmp_path) == []


def test_env_example_reports_missing_key(tmp_path: Path) -> None:
    module = load_module("check_env_example")
    example = tmp_path / ".env.example"
    example.write_text("A=1\n", encoding="utf-8")
    config = tmp_path / "config.py"
    config.write_text('os.getenv("A")\nos.getenv("B")\n', encoding="utf-8")
    declared = module.declared_keys(example)
    used = module.read_keys([config])
    assert sorted(used - declared) == ["B"]


def test_version_consistency_detects_mismatch(tmp_path: Path) -> None:
    module = load_module("check_version_consistency")
    (tmp_path / "pyproject.toml").write_text('version = "2.0.0"\n', encoding="utf-8")
    (tmp_path / "src" / "insurance_audit").mkdir(parents=True)
    (tmp_path / "src" / "insurance_audit" / "__init__.py").write_text(
        '__version__ = "1.9.0"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("## [2.0.0]\n", encoding="utf-8")
    problems = module.find_problems(tmp_path)
    assert any("1.9.0" in problem for problem in problems)

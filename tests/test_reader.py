"""
数据读取层 — 测试套件

重点覆盖 .xls 在缺少 xlrd 时的可读报错：容器/精简环境默认不带 xlrd，
用户拿老格式文件来时要看到「另存为 .xlsx」这类可执行的提示，而不是堆栈。
"""

import sys
from pathlib import Path

import pytest

from insurance_audit.data.reader import read_excel
from insurance_audit.utils.exceptions import FileNotFoundError, IOFailure


class TestReadExcel:
    """Excel 读取测试"""

    @pytest.mark.unit
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """文件不存在 → 自定义 FileNotFoundError（不是内置的）"""
        with pytest.raises(FileNotFoundError):
            read_excel(tmp_path / "not_exists.xlsx")

    @pytest.mark.unit
    def test_xls_without_xlrd_has_friendly_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """.xls 缺 xlrd 时给出「装 xlrd 或另存为 .xlsx」的提示"""
        monkeypatch.setitem(sys.modules, "xlrd", None)  # 模拟 xlrd 不可用
        old_file = tmp_path / "old.xls"
        old_file.write_bytes(b"not a real excel file")

        with pytest.raises(IOFailure) as exc_info:
            read_excel(old_file)

        message = str(exc_info.value)
        assert "xlrd" in message
        assert ".xlsx" in message

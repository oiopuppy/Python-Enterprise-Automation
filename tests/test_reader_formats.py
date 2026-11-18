"""读取层：多格式（Excel/CSV）、多 sheet、编码探测与映射 profile"""

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from insurance_audit.data.reader import (
    build_template,
    detect_encoding,
    init_profile,
    inspect_file,
    list_sheets,
    read_table,
    write_template,
)
from insurance_audit.utils.config import (
    STANDARD_FIELDS,
    ConfigurationError,
    MappingProfile,
    load_profile,
)
from insurance_audit.utils.exceptions import FileNotFoundError, IOFailure

# 客户原始表：英文列名 + 表头前一行说明
ENGLISH_HEADER = [
    "policy_id",
    "insured_name",
    "claim_amount",
    "deductible",
    "payout_ratio",
    "actual_payout",
]

ENGLISH_ROWS = [
    ["CL9900101", "张三", "1000.00", "200.00", "0.80", "640.00"],
    ["CL9900102", "李四", "2000.00", "200.00", "0.80", "1440.00"],
]


def _write_gbk_csv(path: Path, skip_description: bool = False) -> Path:
    lines = [] if skip_description else ["客户理赔台账导出（内部使用）"]
    lines.append(",".join(ENGLISH_HEADER))
    lines.extend(",".join(row) for row in ENGLISH_ROWS)
    path.write_bytes(("\n".join(lines) + "\n").encode("gb18030"))
    return path


def _english_profile(**overrides) -> MappingProfile:
    payload = {
        "role": "ledger",
        "columns": {
            "保单号": "policy_id",
            "客户姓名": "insured_name",
            "报案金额": "claim_amount",
            "免赔额": "deductible",
            "赔付比例": "payout_ratio",
            "实际赔付金额": "actual_payout",
        },
        "primary_key": ["保单号"],
        "skiprows": 1 if overrides.pop("with_description", True) else 0,
        "encoding": "gb18030",
    }
    payload.update(overrides)
    return MappingProfile(**payload)


class TestCsvReading:
    def test_gbk_csv_with_description_row_runs(self, tmp_path):
        """验收①：英文列名 + GBK 编码 + 说明行，只改 profile 就能跑通"""
        path = _write_gbk_csv(tmp_path / "客户台账.csv")
        df = read_table(path, profile=_english_profile())

        assert list(df.columns) == list(STANDARD_FIELDS[:6])
        assert len(df) == 2
        assert df.loc[0, "保单号"] == "CL9900101"
        assert Decimal(str(df.loc[0, "报案金额"])) == Decimal("1000.00")

    def test_encoding_is_detected_automatically(self, tmp_path):
        path = _write_gbk_csv(tmp_path / "客户台账.csv")
        assert detect_encoding(path) in ("gb18030", "utf-8-sig", "utf-8")

    def test_utf8_csv_with_bom(self, tmp_path):
        path = tmp_path / "台账-utf8.csv"
        frame = pd.DataFrame(
            [
                ["CL9900101", "张三", 1000.0, 200.0, 0.8, 640.0],
            ],
            columns=list(STANDARD_FIELDS[:6]),
        )
        frame.to_csv(path, index=False, encoding="utf-8-sig")

        df = read_table(path, profile=MappingProfile())

        assert list(df.columns) == list(STANDARD_FIELDS[:6])
        assert df.loc[0, "客户姓名"] == "张三"

    def test_unsupported_suffix_is_rejected(self, tmp_path):
        path = tmp_path / "台账.json"
        path.write_text("{}", encoding="utf-8")

        with pytest.raises(IOFailure) as info:
            read_table(path, profile=MappingProfile())

        assert ".xlsx" in str(info.value)


class TestExcelSheets:
    def test_sheet_can_be_selected_by_name(self, tmp_path):
        path = tmp_path / "多sheet.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"无关": [1]}).to_excel(writer, sheet_name="说明", index=False)
            pd.DataFrame(
                [["CL9900101", "张三", 1000.0, 200.0, 0.8, 640.0]],
                columns=list(STANDARD_FIELDS[:6]),
            ).to_excel(writer, sheet_name="台账", index=False)

        assert list_sheets(path) == ["说明", "台账"]
        df = read_table(path, sheet="台账", profile=MappingProfile())
        assert list(df.columns) == list(STANDARD_FIELDS[:6])

    def test_missing_sheet_lists_available(self, tmp_path):
        path = tmp_path / "多sheet.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"无关": [1]}).to_excel(writer, sheet_name="说明", index=False)

        with pytest.raises(IOFailure) as info:
            read_table(path, sheet="台账", profile=MappingProfile())

        message = str(info.value)
        assert "台账" in message
        assert "说明" in message


class TestProfile:
    def test_profile_column_missing_reports_line(self, tmp_path):
        """验收②：profile 引用了不存在的列，报错要给出列名与表头行号"""
        path = tmp_path / "台账.csv"
        path.write_bytes(
            (
                "客户理赔台账导出（内部使用）\n"
                + ",".join(ENGLISH_HEADER)
                + "\nCL9900101,张三,1000,200,0.8,640\n"
            ).encode("gb18030")
        )
        profile = _english_profile(columns={"保单号": "policy_no"})

        with pytest.raises(IOFailure) as info:
            read_table(path, profile=profile)

        message = str(info.value)
        assert "policy_no" in message
        assert "第 2 行" in message  # skiprows=1 → 表头在第 2 行
        assert "policy_id" in message  # 实际列名也要给出来

    def test_amount_unit_wan_is_converted(self, tmp_path):
        path = tmp_path / "台账.csv"
        path.write_bytes(
            (",".join(ENGLISH_HEADER) + "\nCL9900101,张三,1.2,0.2,0.8,0.8\n").encode("gb18030")
        )
        profile = _english_profile(with_description=False, amount_unit="wan")
        df = read_table(path, profile=profile)

        assert Decimal(str(df.loc[0, "报案金额"])) == Decimal("12000.00")
        assert Decimal(str(df.loc[0, "实际赔付金额"])) == Decimal("8000.00")

    def test_dates_are_normalized(self, tmp_path):
        path = tmp_path / "台账.csv"
        path.write_bytes(
            (
                ",".join(ENGLISH_HEADER + ["report_date"])
                + "\nCL9900101,张三,1000,200,0.8,640,2026/3/5\n"
            ).encode("gb18030")
        )
        profile = _english_profile(
            with_description=False,
            columns={
                "保单号": "policy_id",
                "客户姓名": "insured_name",
                "报案金额": "claim_amount",
                "免赔额": "deductible",
                "赔付比例": "payout_ratio",
                "实际赔付金额": "actual_payout",
                "报案日期": "report_date",
            },
        )
        df = read_table(path, profile=profile)

        assert df.loc[0, "报案日期"] == "2026-03-05"

    def test_profile_file_is_loaded_and_env_used(self, tmp_path, monkeypatch):
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(
            json.dumps(
                {
                    "columns": {"保单号": "policy_id"},
                    "skiprows": 2,
                    "encoding": "gb18030",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("DATA_PROFILE", str(profile_path))

        profile = load_profile()
        assert profile.columns == {"保单号": "policy_id"}
        assert profile.skiprows == 2

    def test_profile_json_syntax_error_reports_line(self, tmp_path):
        profile_path = tmp_path / "broken.json"
        profile_path.write_text('{"columns": {,}}', encoding="utf-8")

        with pytest.raises(ConfigurationError) as info:
            load_profile(profile_path)

        assert "行" in str(info.value)

    def test_profile_unknown_standard_field_is_rejected(self):
        with pytest.raises(ConfigurationError) as info:
            MappingProfile(columns={"不存在的字段": "x"})
        assert "不存在的字段" in str(info.value)

    def test_profile_primary_key_must_be_standard_field(self):
        with pytest.raises(ConfigurationError):
            MappingProfile(primary_key=("case_id",))

    def test_default_profile_keeps_six_columns(self):
        """验收④：不配 profile 时，现有 6 列台账照旧能跑"""
        profile = MappingProfile()
        assert profile.columns == {}
        assert list(build_template().columns) == list(STANDARD_FIELDS[:6])


class TestTemplate:
    def test_template_has_six_columns_by_default(self, tmp_path):
        """验收③：生成的模板填完能直接跑"""
        path = write_template(tmp_path / "模板.xlsx")
        columns = [str(name) for name in pd.read_excel(path).columns]
        assert columns == list(STANDARD_FIELDS[:6])

    def test_full_template_has_all_standard_fields(self, tmp_path):
        path = write_template(tmp_path / "模板-全.xlsx", full=True)
        columns = [str(name) for name in pd.read_excel(path).columns]
        assert columns == list(STANDARD_FIELDS)

    def test_template_follows_profile_columns(self, tmp_path):
        path = write_template(tmp_path / "模板-客户.xlsx", profile=_english_profile())
        columns = [str(name) for name in pd.read_excel(path).columns]
        assert columns == ENGLISH_HEADER

    def test_csv_template_is_utf8_bom(self, tmp_path):
        path = write_template(tmp_path / "模板.csv")
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")


class TestProfileDraft:
    def test_init_profile_guesses_columns_from_file(self, tmp_path):
        source = _write_gbk_csv(tmp_path / "客户台账.csv")
        out = tmp_path / "profile.json"

        init_profile(out, file_path=source, skiprows=1)
        payload = json.loads(out.read_text(encoding="utf-8"))

        assert payload["columns"]["保单号"] == "policy_id"
        assert payload["columns"]["客户姓名"] == "insured_name"
        assert payload["skiprows"] == 1

    def test_init_profile_without_source_is_default(self, tmp_path):
        out = tmp_path / "profile.json"
        init_profile(out)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["role"] == "ledger"
        assert payload["columns"] == {}


class TestInspect:
    def test_inspect_csv_reports_encoding_and_columns(self, tmp_path):
        path = _write_gbk_csv(tmp_path / "客户台账.csv")
        info = inspect_file(path, skiprows=1)

        assert info["encoding"] in ("gb18030", "utf-8-sig", "utf-8")
        assert info["columns"] == ENGLISH_HEADER
        assert info["rows"] == 2

    def test_inspect_excel_lists_sheets(self, tmp_path):
        path = tmp_path / "多sheet.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="一", index=False)
            pd.DataFrame({"b": [2]}).to_excel(writer, sheet_name="二", index=False)

        info = inspect_file(path)
        assert info["sheets"] == ["一", "二"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_table(tmp_path / "不存在.csv", profile=MappingProfile())


class TestEdgeCases:
    def test_excel_with_numeric_sheet_index(self, tmp_path):
        path = tmp_path / "多sheet.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"说明": ["x"]}).to_excel(writer, sheet_name="封面", index=False)
            pd.DataFrame({name: [] for name in STANDARD_FIELDS[:6]}).to_excel(
                writer, sheet_name="台账", index=False
            )

        df = read_table(path, sheet=1, profile=MappingProfile())

        assert "报告" not in df.columns or len(df) == 0
        assert list(df.columns) == list(STANDARD_FIELDS[:6])

    def test_csv_wrong_explicit_encoding_reports_reason(self, tmp_path):
        path = _write_gbk_csv(tmp_path / "客户台账.csv")

        with pytest.raises(IOFailure) as info:
            read_table(path, encoding="ascii", profile=_english_profile())

        assert "ascii" in str(info.value)

    def test_unsupported_suffix_is_rejected(self, tmp_path):
        path = tmp_path / "台账.json"
        path.write_text("{}", encoding="utf-8")

        with pytest.raises(IOFailure) as info:
            read_table(path, profile=MappingProfile())

        assert "不支持" in str(info.value)

    def test_tab_separated_file_is_sniffed(self, tmp_path):
        path = tmp_path / "台账.tsv"
        lines = ["\t".join(ENGLISH_HEADER)]
        lines.extend("\t".join(row) for row in ENGLISH_ROWS)
        path.write_bytes(("\n".join(lines) + "\n").encode("gb18030"))

        df = read_table(path, profile=_english_profile(with_description=False))

        assert len(df) == 2

    def test_wan_unit_is_scaled(self, tmp_path):
        path = tmp_path / "台账.csv"
        lines = ["policy_id,insured_name,claim_amount,deductible,payout_ratio,actual_payout"]
        lines.append("CL9900101,张三,1.5,0.2,0.80,1.04")
        path.write_bytes(("\n".join(lines) + "\n").encode("gb18030"))

        profile = _english_profile(with_description=False, amount_unit="wan")
        df = read_table(path, profile=profile)

        assert Decimal(str(df.loc[0, "报案金额"])) == Decimal("15000.00")

    def test_unparseable_date_keeps_original(self, tmp_path):
        path = tmp_path / "台账.csv"
        lines = [",".join(ENGLISH_HEADER + ["report_date"])]
        lines.append(",".join(ENGLISH_ROWS[0] + ["不是日期"]))
        path.write_bytes(("\n".join(lines) + "\n").encode("gb18030"))
        profile = _english_profile(
            with_description=False,
            columns={**(_english_profile().columns), "报案日期": "report_date"},
        )

        df = read_table(path, profile=profile)

        assert df.loc[0, "报案日期"] == "不是日期"

    def test_init_profile_from_excel_reads_header(self, tmp_path):
        source = tmp_path / "台账.xlsx"
        pd.DataFrame({name: [] for name in ENGLISH_HEADER}).to_excel(source, index=False)
        out = tmp_path / "profile.json"

        init_profile(out, file_path=source)
        payload = json.loads(out.read_text(encoding="utf-8"))

        assert payload["columns"]["保单号"] == "policy_id"

    def test_cli_print_template_writes_file(self, tmp_path):
        from insurance_audit.data.reader import main

        out = tmp_path / "模板.xlsx"
        code = main(["--print-template", "--out", str(out)])

        assert code == 0
        assert out.exists()

    def test_cli_without_action_prints_help(self, capsys):
        from insurance_audit.data.reader import main

        assert main([]) == 0
        assert "读取层工具" in capsys.readouterr().out

    def test_cli_failure_returns_one(self, tmp_path, capsys):
        from insurance_audit.data.reader import main

        assert main(["--inspect", str(tmp_path / "不存在.csv")]) == 1
        assert "失败" in capsys.readouterr().err

    def test_read_excel_compat_path_still_works(self, tmp_path):
        from insurance_audit.data.reader import read_excel

        path = tmp_path / "台账.xlsx"
        pd.DataFrame(
            {
                "保单号": ["CL9900101"],
                "客户姓名": ["张三"],
                "报案金额": [1000],
                "免赔额": [200],
                "赔付比例": [0.8],
                "实际赔付金额": [640],
            }
        ).to_excel(path, index=False)

        df = read_excel(path)

        assert list(df.columns) == list(STANDARD_FIELDS[:6])
        assert len(df) == 1

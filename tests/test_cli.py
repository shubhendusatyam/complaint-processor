"""Phase 8: the command line entry point.

Exercises argument handling and exit codes with the orchestrator stubbed out,
so no API calls are made.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main as cli
from complaint_processor.schemas import (
    CaseStatus,
    CaseSummary,
    ComplaintCategory,
    ComplaintExtraction,
    CustomerEmail,
    ProcessingResult,
)

EXTRACTED = ComplaintExtraction(
    customer_name="Anita Deshpande",
    email="anita.deshpande@example.com",
    complaint_category=ComplaintCategory.PRODUCT_DEFECT,
    issue_description="No water.",
    is_complaint=True,
    escalation_required=False,
    supporting_document_available=False,
    case_status=CaseStatus.RESOLVED,
)


def good(name="complaint_001.txt") -> ProcessingResult:
    return ProcessingResult(
        filename=name,
        file_type="txt",
        extraction=EXTRACTED,
        customer_email=CustomerEmail(subject="s", body="b"),
        case_summary=CaseSummary(
            case_overview="o",
            key_issue="k",
            action_taken="a",
            current_status="c",
            recommended_next_action="n",
        ),
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A data folder with one file, plus a stubbed workflow builder."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "complaint_001.txt").write_text("a complaint", encoding="utf-8")
    monkeypatch.setattr(cli, "Workflow", type("W", (), {"build": staticmethod(lambda: None)}))
    return tmp_path, data


class TestArguments:
    def test_defaults_come_from_settings(self):
        config = cli.build_settings(cli.parse_args([]))
        assert config.data_dir.name == "data"

    def test_overrides_are_applied_and_resolved(self, tmp_path):
        args = cli.parse_args(
            ["--data-dir", str(tmp_path), "--workers", "7", "--log-level", "DEBUG"]
        )
        config = cli.build_settings(args)
        assert config.data_dir == tmp_path.resolve()
        assert config.max_workers == 7
        assert config.log_level == "DEBUG"

    def test_rejects_an_unknown_log_level(self):
        with pytest.raises(SystemExit):
            cli.parse_args(["--log-level", "CHATTY"])


class TestExitCodes:
    def test_zero_when_every_document_succeeds(self, workspace, monkeypatch, capsys):
        tmp_path, data = workspace
        monkeypatch.setattr(cli, "process_batch", lambda **kw: [good()])

        code = cli.main(["--data-dir", str(data), "--output-dir", str(tmp_path / "out")])

        assert code == 0
        assert "Processed 1 document" in capsys.readouterr().out

    def test_one_when_a_document_fails(self, workspace, monkeypatch):
        """A scripted run needs to detect a partial batch."""
        tmp_path, data = workspace
        monkeypatch.setattr(
            cli,
            "process_batch",
            lambda **kw: [good(), ProcessingResult.failure("bad.pdf", "pdf", "unreadable")],
        )
        code = cli.main(["--data-dir", str(data), "--output-dir", str(tmp_path / "out")])
        assert code == 1

    def test_one_when_there_is_nothing_to_process(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(cli, "Workflow", type("W", (), {"build": staticmethod(lambda: None)}))
        monkeypatch.setattr(cli, "process_batch", lambda **kw: [])
        code = cli.main(["--data-dir", str(empty), "--output-dir", str(tmp_path / "out")])
        assert code == 1

    def test_two_when_the_input_folder_is_missing(self, tmp_path, capsys):
        code = cli.main(["--data-dir", str(tmp_path / "nope"), "--output-dir", str(tmp_path)])
        assert code == 2
        assert "Configuration problem" in capsys.readouterr().err


class TestOutput:
    def test_writes_the_artifacts_and_names_them(self, workspace, monkeypatch, capsys):
        tmp_path, data = workspace
        out = tmp_path / "out"
        monkeypatch.setattr(cli, "process_batch", lambda **kw: [good()])

        cli.main(["--data-dir", str(data), "--output-dir", str(out)])

        assert (out / "structured_data" / "complaint_001.json").is_file()
        assert (out / "final_report.csv").is_file()
        printed = capsys.readouterr().out
        assert "final_report.csv" in printed
        assert "structured_data/" in printed

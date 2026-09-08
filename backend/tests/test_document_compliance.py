from __future__ import annotations

from app.core.config import settings
from app.documents.rules import load_rules
from app.documents.scanner import scan_texts
from app.documents.schemas import ComplianceReport
from app.documents.service import ComplianceService
from app.documents.storage import save_upload


class FakeJudge:
    def __init__(self, report: ComplianceReport, *, fail: bool = False) -> None:
        self._report = report
        self._fail = fail

    async def judge(self, prompt: str) -> ComplianceReport:
        if self._fail:
            raise RuntimeError("judge unavailable")
        return self._report


async def _assess_text(tmp_path, monkeypatch, text: str, judge) -> ComplianceReport:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    meta = save_upload(
        file_name="note.txt",
        content_type="text/plain",
        data=text.encode("utf-8"),
    )
    service = ComplianceService(judge=judge)
    return await service.assess(meta["upload_id"])


def test_scanner_finds_high_severity_ssn() -> None:
    rules = load_rules()
    hits = scan_texts([(1, "My social security number is 123-45-6789.")], rules)
    ssn = [h for h in hits if h.rule == "us_ssn"]
    assert ssn and ssn[0].severity == "high"
    assert ssn[0].page == 1


async def test_assess_clean_document_is_compliant(tmp_path, monkeypatch) -> None:
    judge = FakeJudge(
        ComplianceReport(
            overall_compliant=True,
            risk_level="low",
            summary="Nothing sensitive found.",
        )
    )
    report = await _assess_text(
        tmp_path, monkeypatch, "The quick brown fox jumps over the lazy dog.", judge
    )
    assert report.overall_compliant is True
    assert report.risk_level == "low"


async def test_high_severity_scan_overrides_llm_verdict(tmp_path, monkeypatch) -> None:
    judge = FakeJudge(
        ComplianceReport(
            overall_compliant=True,
            risk_level="low",
            summary="Model missed the SSN.",
        )
    )
    report = await _assess_text(
        tmp_path, monkeypatch, "My social security number is 123-45-6789.", judge
    )
    assert report.overall_compliant is False
    assert report.risk_level == "high"
    assert any(f.category and f.severity == "high" for f in report.findings)
    assert any("high-severity" in w for w in report.warnings)


async def test_assess_falls_back_when_judge_fails(tmp_path, monkeypatch) -> None:
    judge = FakeJudge(
        ComplianceReport(overall_compliant=True, risk_level="low"), fail=True
    )
    report = await _assess_text(
        tmp_path, monkeypatch, "Reach me at test@example.com.", judge
    )
    assert any("automated scans" in w for w in report.warnings)
    assert report.overall_compliant is True  # no high-severity automated hits

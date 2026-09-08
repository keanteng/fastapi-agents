from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high"]


class PageText(BaseModel):
    """Extracted text for a single document page."""

    page_no: int
    text: str
    scanned: bool = Field(
        default=False, description="True when text came from OCR of the page image."
    )


class ExtractedDocument(BaseModel):
    """The result of the textract-style text extraction pass."""

    file_name: str
    kind: str
    pages: list[PageText] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


class ScanHit(BaseModel):
    """A regex-level sensitive-data hit found by the automated scanner."""

    rule: str
    category: str
    severity: Severity = "medium"
    page: int | None = None
    evidence: str = ""
    reason: str = ""
    recommendation: str = ""


class ComplianceFinding(BaseModel):
    """A single reason a document may not be compliant."""

    category: str
    severity: Severity = "medium"
    page: int | None = None
    evidence: str = ""
    reason: str = ""
    recommendation: str = ""


class VisualFinding(BaseModel):
    """A compliance-relevant observation from analysing a page image."""

    page: int | None = None
    description: str = ""
    reason: str = ""
    severity: Severity = "medium"


class ComplianceReport(BaseModel):
    """Structured verdict for a document compliance check."""

    overall_compliant: bool
    risk_level: Severity = "low"
    summary: str = ""
    findings: list[ComplianceFinding] = Field(default_factory=list)
    visual_findings: list[VisualFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic_ai import Agent

from app.core.config import settings
from app.core.model import get_model
from app.core.prompts import render
from app.documents import extraction as extraction_mod
from app.documents.rules import SensitiveRule, load_rules
from app.documents.scanner import scan_texts
from app.documents.schemas import (
    ComplianceFinding,
    ComplianceReport,
    ExtractedDocument,
    ScanHit,
    VisualFinding,
)
from app.documents.storage import get_upload
from app.documents.vision import VisionAnalyzer

Emit = Callable[[str], Awaitable[None]]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…[truncated]"


class LLMJudge:
    """Runs the compliance verdict pass with the text chat model."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = model or get_model()

    async def judge(self, user_prompt: str) -> ComplianceReport:
        agent = Agent(
            self._model,
            output_type=ComplianceReport,
            instructions=lambda _: render("compliance_verdict"),
        )
        async with agent:
            result = await agent.run(user_prompt)
        return result.output  # type: ignore[no-any-return]


def _scanner_fallback_report(
    hits: list[ScanHit],
    warnings: list[str],
    vision_findings: list[VisualFinding],
) -> ComplianceReport:
    """Synthesize a report from the automated scan when the LLM verdict fails."""
    high = [h for h in hits if h.severity == "high"]
    return ComplianceReport(
        overall_compliant=not high,
        risk_level="high" if high else "medium",
        summary=(
            "The automated scan flagged sensitive material, so the document "
            "cannot be confirmed compliant."
            if high
            else "No high-severity sensitive material was detected by automated scans."
        ),
        findings=[
            ComplianceFinding(
                category=h.category,
                severity=h.severity,
                page=h.page,
                evidence=h.evidence,
                reason=h.reason,
                recommendation=h.recommendation,
            )
            for h in hits
        ],
        visual_findings=vision_findings,
        warnings=warnings
        + ["LLM judgement failed; report is based on automated scans only."],
    )


class ComplianceService:
    """Orchestrates text extraction, scanning, visual analysis and verdict."""

    def __init__(
        self,
        *,
        rules: Sequence[SensitiveRule] | None = None,
        vision: VisionAnalyzer | None = None,
        judge: Any | None = None,
        max_text_chars: int | None = None,
    ) -> None:
        self._rules = list(rules) if rules is not None else load_rules(
            settings.compliance_rules_path
        )
        self._vision = vision or build_vision_analyzer_default()
        self._judge = judge or LLMJudge()
        self._max_text_chars = max_text_chars or settings.compliance_max_text_chars

    async def assess(self, upload_id: str, emit: Emit | None = None) -> ComplianceReport:
        async def _progress(message: str) -> None:
            if emit is not None:
                await emit(message)

        record = get_upload(upload_id)
        path = record["path"]
        meta = record["meta"]
        file_name = meta.get("file_name", "document")
        ext = file_name.rsplit(".", maxsplit=1)[-1].lower() if "." in file_name else ""

        await _progress(f"Analysing {file_name}…")
        document = await self._extract(path, file_name, ext, _progress)

        await _progress("Scanning text for PII / sensitive data…")
        hits = scan_texts([(p.page_no, p.text) for p in document.pages], self._rules)

        warnings: list[str] = []
        vision_findings: list[VisualFinding] = []
        visual_pages = extraction_mod.render_visual_pages(
            path, ext, self._vision.max_pages if self._vision.enabled else 0
        )
        if visual_pages:
            await _progress(
                f"Analysing up to {len(visual_pages)} page image(s) with vision…"
            )
            vision_findings, vision_warnings = await self._vision.analyze(visual_pages)
            warnings.extend(vision_warnings)

        await _progress("Assessing compliance verdict…")
        report = await self._judge_report(document, hits, vision_findings)

        report.visual_findings = vision_findings
        warnings = self._attach_warnings(warnings, document, visual_pages)
        report.warnings = list(dict.fromkeys([*warnings, *report.warnings]))

        report = self._reconcile_scan_hits(report, hits)
        return report

    # ------------------------------------------------------------------ #

    async def _extract(
        self,
        path: Any,
        file_name: str,
        ext: str,
        progress: Emit,
    ) -> ExtractedDocument:
        # Run the CPU-bound extraction in a worker thread.
        import asyncio

        await progress("Extracting text…")
        document = await asyncio.to_thread(
            extraction_mod.extract_text, path, file_name
        )
        scanned = [p.page_no for p in document.pages if p.scanned]
        if scanned:
            await progress(
                f"OCR applied to scanned page(s): {', '.join(map(str, scanned))}"
            )
        return document

    async def _judge_report(
        self,
        document: ExtractedDocument,
        hits: list[ScanHit],
        vision_findings: list[VisualFinding],
    ) -> ComplianceReport:
        user_prompt = self._build_prompt(document, hits, vision_findings)
        try:
            return await self._judge.judge(user_prompt)
        except Exception:
            warnings = [
                "LLM judgement failed; report is based on automated scans only."
            ]
            return _scanner_fallback_report(hits, warnings, vision_findings)

    def _build_prompt(
        self,
        document: ExtractedDocument,
        hits: list[ScanHit],
        vision_findings: list[VisualFinding],
    ) -> str:
        hit_lines = []
        for hit in hits[:50]:
            page = f"page {hit.page}" if hit.page else "unknown page"
            hit_lines.append(
                f"- [{hit.severity}] {hit.category} ({hit.rule}) {page}: "
                f"{hit.evidence}"
            )
        hits_text = "\n".join(hit_lines) or "(none detected by automated scan)"
        vision_lines = [
            f"- page {f.page}: {f.description}" if f.page else f"- {f.description}"
            for f in vision_findings
        ]
        vision_text = "\n".join(vision_lines) or "(no visual analysis available)"
        text = _truncate(document.full_text, self._max_text_chars)
        return json.dumps(
            {
                "file_name": document.file_name,
                "pages": len(document.pages),
                "automated_scan_hits": hits_text,
                "visual_analysis": vision_text,
                "document_text": text,
            },
            ensure_ascii=False,
        )

    def _attach_warnings(
        self,
        warnings: list[str],
        document: ExtractedDocument,
        visual_pages: list[Any],
    ) -> list[str]:
        if visual_pages and not self._vision.enabled:
            warnings.append("visual analysis is disabled")
        return warnings

    @staticmethod
    def _reconcile_scan_hits(
        report: ComplianceReport, hits: list[ScanHit]
    ) -> ComplianceReport:
        """Never let a high-severity scan hit be silently ignored by the LLM."""
        high = [h for h in hits if h.severity == "high"]
        if not high:
            return report
        covered = {f.category.lower() for f in report.findings}
        missed = [h for h in high if h.category.lower() not in covered]
        if report.overall_compliant or missed:
            report.overall_compliant = False
            report.risk_level = "high"
            report.warnings.append(
                "Automated scan found high-severity sensitive data; verdict overridden."
            )
            report.findings.extend(
                ComplianceFinding(
                    category=h.category,
                    severity=h.severity,
                    page=h.page,
                    evidence=h.evidence,
                    reason=h.reason,
                    recommendation=h.recommendation,
                )
                for h in missed
            )
        return report


def build_vision_analyzer_default() -> VisionAnalyzer:
    from app.documents.vision import build_vision_analyzer

    return build_vision_analyzer()


def build_compliance_service(**overrides: Any) -> ComplianceService:
    return ComplianceService(**overrides)

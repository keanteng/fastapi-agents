from __future__ import annotations

import re
from collections.abc import Iterable

from app.documents.rules import SensitiveRule
from app.documents.schemas import ScanHit

# Cap on hits kept per rule per page to bound prompt size / noise.
_MAX_HITS_PER_RULE_PAGE = 3
_SNIPPET_RADIUS = 60


def _snippet(text: str, start: int, end: int, radius: int = _SNIPPET_RADIUS) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].replace("\n", " ")
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet


def scan_texts(
    pages: Iterable[tuple[int, str]], rules: list[SensitiveRule]
) -> list[ScanHit]:
    """Run every rule over each page, returning capped, de-duplicated hits."""
    hits: list[ScanHit] = []
    counters: dict[tuple[str, int], int] = {}
    for page_no, text in pages:
        for rule in rules:
            pattern = rule.compile()
            key = (rule.name, page_no)
            seen: set[tuple[int, int]] = set()
            count = counters.get(key, 0)
            for match in pattern.finditer(text):
                if count >= _MAX_HITS_PER_RULE_PAGE:
                    break
                span = match.span()
                if span in seen:
                    continue
                seen.add(span)
                evidence = _snippet(text, span[0], span[1])
                if len(evidence) < 3:
                    continue
                hits.append(
                    ScanHit(
                        rule=rule.name,
                        category=rule.category,
                        severity=rule.severity,
                        page=page_no,
                        evidence=evidence,
                        reason=rule.reason,
                        recommendation=rule.recommendation,
                    )
                )
                count += 1
            counters[key] = count
    return hits

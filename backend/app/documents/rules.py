from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.documents.schemas import Severity


class SensitiveRule(BaseModel):
    """A sensitive-data rule: regex + metadata used by the scanner and judge."""

    name: str
    category: str
    severity: Severity = "medium"
    pattern: str = Field(..., description="Regular expression (re.search is enough).")
    reason: str = ""
    recommendation: str = ""

    def compile(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE)


DEFAULT_RULES: list[SensitiveRule] = [
    SensitiveRule(
        name="email_address",
        category="PII - contact",
        severity="low",
        pattern=r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        reason="Email addresses are personal data.",
        recommendation="Review whether the email is necessary and consensually published.",
    ),
    SensitiveRule(
        name="phone_number",
        category="PII - contact",
        severity="low",
        pattern=r"(?<!\w)(?:\+?\d[\d\s().\-/]{7,}\d)(?!\w)",
        reason="Phone numbers are personal data.",
        recommendation="Confirm consent/legitimate purpose before publishing.",
    ),
    SensitiveRule(
        name="us_ssn",
        category="PII - government ID",
        severity="high",
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
        reason="A US Social Security number is highly sensitive personal data.",
        recommendation="Remove or fully redact the number.",
    ),
    SensitiveRule(
        name="us_passport",
        category="PII - government ID",
        severity="high",
        pattern=r"\b(?:passport\s*(?:no\.?|number)?\s*[:#-]?\s*)?[A-Z]\d{8}\b",
        reason="Passport numbers are sensitive government identifiers.",
        recommendation="Remove or fully redact the passport number.",
    ),
    SensitiveRule(
        name="credit_card_number",
        category="Financial data",
        severity="high",
        pattern=r"\b(?:\d[ -]?){13,19}\b",
        reason="Card-like number sequence. Confirm it is not a payment card.",
        recommendation="Remove card numbers; storing payment card data requires PCI DSS controls.",
    ),
    SensitiveRule(
        name="iban",
        category="Financial data",
        severity="medium",
        pattern=r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
        reason="IBANs expose bank account details.",
        recommendation="Only include bank details where required and authorised.",
    ),
    SensitiveRule(
        name="aws_access_key",
        category="Credentials / secrets",
        severity="high",
        pattern=r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        reason="An AWS access key id looks present.",
        recommendation="Rotate the key and remove it from the document.",
    ),
    SensitiveRule(
        name="private_key",
        category="Credentials / secrets",
        severity="high",
        pattern=r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----",
        reason="A private key block appears to be present.",
        recommendation="Remove private key material immediately.",
    ),
    SensitiveRule(
        name="secret_assignment",
        category="Credentials / secrets",
        severity="high",
        pattern=r"\b(?:api[_-]?key|secret|password|passwd|token|authorization)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}",
        reason="A hard-coded secret/token assignment looks present.",
        recommendation="Remove secrets; use a secret store instead.",
    ),
    SensitiveRule(
        name="national_id_generic",
        category="PII - government ID",
        severity="medium",
        pattern=r"\b\d{3,4}[\s-]?\d{3,4}[\s-]?\d{3,4}\b",
        reason="Possible national/generic identity number format.",
        recommendation="Verify whether this is a government-issued identifier.",
    ),
    SensitiveRule(
        name="date_of_birth",
        category="PII - personal",
        severity="low",
        pattern=r"\b(?:DOB|date\s*of\s*birth|born(?:\s+on)?)\s*[:#]?\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b",
        reason="Date of birth is personal data.",
        recommendation="Confirm it is required before publishing.",
    ),
]


def load_rules(path: str | None = None) -> list[SensitiveRule]:
    """Return the built-in rules plus any overrides from a YAML file.

    The optional file is a list under a ``rules:`` key; each entry mirrors a
    ``SensitiveRule`` and is appended to the defaults.
    """
    rules = list(DEFAULT_RULES)
    if not path:
        return rules
    from yaml import safe_load

    with Path(path).open(encoding="utf-8") as fh:
        payload = safe_load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"compliance rules file {path} must map to a dict")
    extra = payload.get("rules") or []
    if not isinstance(extra, list):
        raise ValueError(f"compliance rules file {path} must contain a 'rules' list")
    for item in extra:
        rules.append(SensitiveRule.model_validate(item))
    return rules


def rules_to_prompt(rules: list[SensitiveRule]) -> str:
    """Render the rule set into a compact prompt fragment."""
    lines = []
    for rule in rules:
        lines.append(
            f"- {rule.name} [{rule.category}, {rule.severity}]: {rule.reason} "
            f"-> {rule.recommendation}"
        )
    return "\n".join(lines) if lines else "(no rules configured)"

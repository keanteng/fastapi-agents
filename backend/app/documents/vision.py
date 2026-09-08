from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Iterable

import httpx

from app.documents.schemas import VisualFinding


class VisionUnavailableError(Exception):
    """Raised when visual analysis is configured but cannot run."""


class VisionAnalyzer:
    """Analyse page images with a DeepSeek vision model.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint with inline
    base64 JPEG images (the ``deepseek-v4-flash-vision-exp`` model). Degrades
    gracefully when disabled: callers receive ``[]`` and a warning instead of
    an error.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        enabled: bool = True,
        max_pages: int = 8,
        concurrency: int = 3,
        timeout: float = 60.0,
        prompt_factory: Callable[[], str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._max_pages = max_pages
        self._concurrency = concurrency
        self._timeout = timeout
        self._prompt_factory = prompt_factory or self._default_prompt

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._api_key) and self._api_key != "stub"

    @property
    def max_pages(self) -> int:
        return self._max_pages

    def _default_prompt(self) -> str:
        from app.core.prompts import get_engine

        return get_engine().render("compliance_visual_analysis")

    def _image_url(self, jpeg: bytes) -> str:
        encoded = base64.b64encode(jpeg).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    async def _analyze_one(self, client: httpx.AsyncClient, jpeg: bytes) -> str:
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._prompt_factory()},
                        {
                            "type": "image_url",
                            "image_url": {"url": self._image_url(jpeg), "detail": "low"},
                        },
                    ],
                }
            ],
        }
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        choices = (body.get("choices") or [])
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content", "") or ""
        if isinstance(content, list):
            return " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content).strip()

    async def analyze(
        self,
        pages: Iterable[tuple[int, bytes]],
    ) -> tuple[list[VisualFinding], list[str]]:
        """Analyse up to ``max_pages`` images; returns (findings, warnings)."""
        if not self.enabled:
            return [], [
                "visual analysis is disabled or no vision model is configured"
            ]
        selected = list(pages)[: self._max_pages]
        if not selected:
            return [], []

        semaphore = asyncio.Semaphore(self._concurrency)

        async def _bounded(page_no: int, jpeg: bytes) -> tuple[int, str]:
            async with semaphore:
                async with httpx.AsyncClient() as client:
                    note = await self._analyze_one(client, jpeg)
                return page_no, note

        tasks = [_bounded(page_no, jpeg) for page_no, jpeg in selected]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        findings: list[VisualFinding] = []
        warnings: list[str] = []
        for page_no, outcome in zip([p for p, _ in selected], results, strict=False):
            if isinstance(outcome, Exception):
                warnings.append(f"page {page_no} visual analysis failed: {outcome}")
                continue
            note = (outcome or "").strip()
            if note:
                findings.append(
                    VisualFinding(page=page_no, description=note[:2000], reason="")
                )
        return findings, warnings


def build_vision_analyzer() -> VisionAnalyzer:
    from app.core.config import settings

    return VisionAnalyzer(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.doc_vision_model,
        enabled=settings.doc_vision_enabled,
        max_pages=settings.doc_max_vision_pages,
    )

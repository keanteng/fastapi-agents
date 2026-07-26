from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


TEMPLATE_ROOT = Path(__file__).resolve().parent.parent  # the ``app`` package


@lru_cache(maxsize=1)
def get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(template_name: str, /, **context: Any) -> str:
    """Render a template prefixed by its slice folder."""
    return get_env().get_template(template_name).render(**context)

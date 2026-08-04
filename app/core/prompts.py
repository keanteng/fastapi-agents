from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

APP_ROOT = Path(__file__).resolve().parent.parent  # the ``app`` package
PROMPTS_CONFIG = Path(__file__).resolve().parent / "prompts.yml"


class PromptEngine:
    """Renders Jinja2 prompt templates resolved by a YAML catalog."""

    def __init__(
        self,
        templates_root: Path = APP_ROOT,
        config_path: Path = PROMPTS_CONFIG,
    ) -> None:
        self.templates_root = Path(templates_root)
        self.config_path = Path(config_path)
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_root)),
            autoescape=select_autoescape(default=False),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._catalog = self._load_catalog()

    def _load_catalog(self) -> dict[str, dict[str, dict[str, str]]]:
        from yaml import safe_load

        with open(self.config_path, encoding="utf-8") as fh:
            catalog = safe_load(fh)
        if not isinstance(catalog, dict):
            raise ValueError(f"prompt catalog {self.config_path} is empty or invalid")
        for task, variants in catalog.items():
            for variant, cfg in variants.items():
                path = cfg.get("path")
                if not isinstance(path, str) or not path:
                    raise ValueError(
                        f"prompt {task!r}/{variant!r} is missing a 'path' entry"
                    )
                if not (self.templates_root / path).exists():
                    raise FileNotFoundError(
                        f"prompt template missing: '{path}' "
                        f"(task={task!r}, variant={variant!r})"
                    )
        return catalog

    def render(self, task: str, variant: str | None = None, **context: Any) -> str:
        """Render the template for ``task``/``variant`` with ``context``."""
        variants = self._catalog.get(task)
        if variants is None:
            raise KeyError(
                f"unknown prompt task {task!r}; available: {sorted(self._catalog)}"
            )
        key = variant or "default"
        cfg = variants.get(key)
        if cfg is None:
            raise KeyError(f"no variant {key!r} for prompt task {task!r}")
        return self._env.get_template(cfg["path"]).render(**context)

    def available_tasks(self) -> list[str]:
        return sorted(self._catalog)


def get_engine() -> PromptEngine:
    """Return the process-wide prompt engine (owned by the app container)."""
    from app.core.container import get_container

    return get_container().prompts


def render(task: str, variant: str | None = None, **context: Any) -> str:
    """Render a catalogued prompt by ``task``/``variant`` (see ``prompts.yml``)."""
    return get_engine().render(task, variant, **context)

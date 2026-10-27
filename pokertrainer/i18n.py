"""Idioma da interface (português / inglês).

Os textos ficam lado a lado no código: `tr("Mesa", "Table")`. Ao trocar de idioma, a janela é reconstruída.
"""

from __future__ import annotations

LANGUAGES = {"pt": "Português", "en": "English"}
_lang = "pt"


def lang() -> str:
    return _lang


def set_lang(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "pt"


def tr(pt: str, en: str) -> str:
    return en if _lang == "en" else pt


def pick(pt, en):
    """Como `tr`, para qualquer valor (listas, dicionários…)."""
    return en if _lang == "en" else pt

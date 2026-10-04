"""The backend's texts in Spanish and English (VIG-40, ADR-0008).

One JSON file per language in `locales/`, with the same conventions as the dashboard's: nested
keys and `{{name}}` placeholders, so translators work with a single format. A test holds every
language to Spanish: the same keys and the same placeholders.
"""

import json
import re
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from willay.shared.errors import Names, Term
from willay.shared.languages import DEFAULT_LANGUAGE, Language

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_LANGUAGE_RANGE = re.compile(
    r"^\s*([A-Za-z]{1,8})(?:-[A-Za-z0-9]{1,8})*\s*(?:;\s*q\s*=\s*([0-9.]+))?\s*$"
)


def _flatten(node: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in node.items():
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = str(value)
    return flat


def _load(language: Language) -> dict[str, str]:
    text = (files("willay.shared") / "locales" / f"{language.value}.json").read_text("utf-8")
    return _flatten(json.loads(text))


CATALOGS: Mapping[Language, Mapping[str, str]] = {
    language: _load(language) for language in Language
}


def translate(key: str, language: Language, **params: object) -> str:
    """The text of `key` in `language`, with its placeholders filled. A missing key falls back
    to Spanish, and then to the key itself: a client never gets an empty message."""
    template = CATALOGS[language].get(key) or CATALOGS[DEFAULT_LANGUAGE].get(key) or key

    def fill(match: re.Match[str]) -> str:
        value = params.get(match.group(1), match.group(0))
        if isinstance(value, Term):
            return translate(value, language)
        if isinstance(value, Names):
            return ", ".join(translate("format.quote", language, text=name) for name in value)
        return str(value)

    return _PLACEHOLDER.sub(fill, template)


def negotiate(accept_language: str | None) -> Language:
    """The language of an `Accept-Language` header that Willay speaks, by preference
    ("en-GB,en;q=0.9" → English), else Spanish."""
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate((accept_language or "").split(",")):
        match = _LANGUAGE_RANGE.match(part)
        if match is None:
            continue
        try:
            quality = float(match.group(2)) if match.group(2) else 1.0
        except ValueError:
            continue
        ranked.append((-quality, position, match.group(1).lower()))
    for _, _, tag in sorted(ranked):
        if tag in Language._value2member_map_:
            return Language(tag)
    return DEFAULT_LANGUAGE

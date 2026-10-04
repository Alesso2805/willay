"""VIG-40: the backend's texts in Spanish and English."""

import re

import pytest

from willay.shared.errors import ErrorCode, Names, Term
from willay.shared.i18n import CATALOGS, negotiate, translate
from willay.shared.languages import Language

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@pytest.mark.parametrize(
    ("header", "language"),
    [
        ("en-GB,en;q=0.9,es;q=0.8", Language.EN),
        ("es-PE,es;q=0.9,en;q=0.8", Language.ES),
        ("fr-FR,fr;q=0.9,en;q=0.5", Language.EN),  # the first one Willay speaks
        ("en;q=0.2,es;q=0.9", Language.ES),  # by quality, not by position
        ("fr, de", Language.ES),
        ("", Language.ES),
        (None, Language.ES),
        ("en;q=abc, ???", Language.ES),  # unreadable parts are skipped
    ],
)
def test_the_language_follows_accept_language(header: str | None, language: Language) -> None:
    assert negotiate(header) is language


def test_placeholders_are_filled_and_terms_translated_in_the_same_language() -> None:
    assert translate("errors.rate_limited", Language.EN, max=60) == (
        "Limit of 60 batches per minute per station"
    )
    status, action = Term("incident_status.resolved"), Term("incident_action.acknowledge")
    assert translate("errors.incident_transition", Language.ES, status=status, action=action) == (
        "El incidente ya está resuelto: no se puede confirmar."
    )
    assert translate("errors.incident_transition", Language.EN, status=status, action=action) == (
        "The incident is already resolved: it cannot be acknowledged."
    )


def test_names_are_quoted_the_way_each_language_quotes() -> None:
    names = Names(["Protocolo Rímac", "Plan B"])
    assert translate("errors.group_in_use", Language.ES, group="Brigada", policies=names) == (
        "Brigada se usa en «Protocolo Rímac», «Plan B». Quítalo de esa política antes de borrarlo."
    )
    english = translate("errors.group_in_use", Language.EN, group="Brigada", policies=names)
    assert english.startswith("Brigada is used by “Protocolo Rímac”, “Plan B”.")


def test_a_missing_key_never_yields_an_empty_message() -> None:
    assert translate("errors.no_such_code", Language.EN) == "errors.no_such_code"


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_has_a_text_in_every_language(code: ErrorCode) -> None:
    for language in Language:
        assert CATALOGS[language].get(f"errors.{code}"), (language, code)


@pytest.mark.parametrize("language", list(Language))
def test_every_language_has_exactly_the_texts_and_placeholders_of_spanish(
    language: Language,
) -> None:
    spanish = CATALOGS[Language.ES]
    assert sorted(CATALOGS[language]) == sorted(spanish)
    for key, text in CATALOGS[language].items():
        assert text.strip(), key
        assert set(_PLACEHOLDER.findall(text)) == set(_PLACEHOLDER.findall(spanish[key])), key

"""The languages Willay speaks. Adding one means adding it here, to the database
CHECK constraints and to the translation files; the code reads the list from here."""

from enum import StrEnum


class Language(StrEnum):
    ES = "es"
    EN = "en"


DEFAULT_LANGUAGE = Language.ES

"""Severity of a rule, copied to each incident it opens (CHECK on rules and incidents)."""

from enum import StrEnum


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

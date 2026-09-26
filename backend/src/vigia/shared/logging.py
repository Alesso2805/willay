"""Logs JSON con structlog, un evento por línea."""

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            # Permite `bind_contextvars(correlation_id=...)` una vez y verlo en todos los logs.
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        cache_logger_on_first_use=True,
    )

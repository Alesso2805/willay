"""JSON logs with structlog, one event per line."""

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            # Lets `bind_contextvars(correlation_id=...)` be bound once and show in every log.
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

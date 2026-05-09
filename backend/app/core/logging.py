import structlog
import logging


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if debug
            else structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=True,
    )

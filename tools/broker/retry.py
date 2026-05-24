"""Retry wrapper with exponential backoff for broker API calls."""

import time
import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    max_retries: int = 10
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0


def with_retry(
    fn: Callable[..., T],
    config: RetryConfig | None = None,
    retryable: tuple[type[Exception], ...] = (Exception,),
) -> Callable[..., T]:
    """Wrap a function with retry logic. Returns a new callable."""
    cfg = config or RetryConfig()

    def wrapper(*args, **kwargs) -> T:
        last_exc: Exception | None = None
        delay = cfg.base_delay

        for attempt in range(cfg.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except retryable as e:
                last_exc = e
                if attempt == cfg.max_retries:
                    break
                logger.warning(
                    "Retry %d/%d: %s (delay=%.1fs)",
                    attempt + 1, cfg.max_retries, e, delay,
                )
                time.sleep(delay)
                delay = min(delay * cfg.backoff_multiplier, cfg.max_delay)

        raise last_exc  # type: ignore

    return wrapper

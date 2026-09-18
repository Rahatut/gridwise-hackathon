"""
Thread-safe Gemini client pool with credential failover and budget-aware retry.

Rate Limit Note:
Google Gemini API rate limits (RPM/TPM/RPD) are enforced per Google Cloud / AI Studio
PROJECT, not per individual API key generated within the same project. Therefore,
multiple API keys generated within the same project share identical quota limits.
This pool is designed for reliable failover across authorized credentials from independent
projects and graceful cooldown handling, never for circumventing provider quotas.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Type

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Raised when LLM provider operations fail, keys are exhausted, or output is invalid."""
    pass


@dataclass
class KeyEntry:
    key: str
    key_id: str  # Safe sanitized identifier, e.g. "key_1"
    client: genai.Client
    cooldown_until: float = 0.0
    disabled: bool = False
    consecutive_failures: int = 0


def parse_api_keys() -> List[str]:
    """
    Parse Gemini API keys from environment variables.

    Rules:
    - GEMINI_API_KEYS (comma-separated) wins if provided and non-empty.
    - GEMINI_API_KEY is used as single-key fallback.
    - Whitespace is trimmed, empty entries ignored.
    - Duplicate keys are discarded while preserving order.
    - Keys are never logged or echoed in exceptions.
    """
    raw_multi = os.getenv("GEMINI_API_KEYS")
    if raw_multi is not None and raw_multi.strip():
        parts = raw_multi.split(",")
    else:
        single = os.getenv("GEMINI_API_KEY", "")
        parts = [single] if single.strip() else []

    deduped: List[str] = []
    seen = set()
    for p in parts:
        cleaned = p.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            deduped.append(cleaned)
    return deduped


def _sanitize_message(msg: str, keys: Sequence[str]) -> str:
    """Ensure no raw API key string leaks into error messages or logs."""
    sanitized = str(msg)
    for k in keys:
        if k and len(k) >= 6 and k in sanitized:
            sanitized = sanitized.replace(k, "[REDACTED_API_KEY]")
    return sanitized


class GeminiKeyPool:
    """
    Thread-safe pool of persistent Gemini clients with round-robin selection,
    per-key cooldown tracking, and permanent disabling for bad credentials.
    """

    def __init__(self, keys: Sequence[str]):
        if not keys:
            raise LLMProviderError(
                "No valid Gemini API keys configured. Set GEMINI_API_KEYS or GEMINI_API_KEY in the environment."
            )
        self._lock = threading.Lock()
        self._current_index = 0
        self._entries: List[KeyEntry] = []

        for idx, k in enumerate(keys):
            key_id = f"key_{idx + 1}"
            # Configure HttpOptions with attempts=1 so our failover pool manages rotation
            http_opts = types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            client = genai.Client(api_key=k, http_options=http_opts)
            self._entries.append(
                KeyEntry(
                    key=k,
                    key_id=key_id,
                    client=client,
                )
            )

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def all_keys(self) -> List[str]:
        with self._lock:
            return [e.key for e in self._entries]

    def get_candidate(self, excluded_ids: Optional[set[str]] = None) -> KeyEntry:
        """
        Select the next available healthy key in round-robin fashion.
        Skips disabled keys, excluded keys, and keys currently in cooldown.
        Raises LLMProviderError if no key is ready.
        """
        excluded = excluded_ids or set()
        now = time.monotonic()

        with self._lock:
            total = len(self._entries)
            available = [e for e in self._entries if not e.disabled]
            if not available:
                raise LLMProviderError(
                    "All Gemini API credentials have been disabled due to authentication errors."
                )

            # 1. Look for an available key not excluded and not in cooldown
            for offset in range(total):
                idx = (self._current_index + offset) % total
                entry = self._entries[idx]
                if entry.disabled or entry.key_id in excluded:
                    continue
                if entry.cooldown_until <= now:
                    self._current_index = (idx + 1) % total
                    return entry

            # 2. If all non-excluded keys are cooling down, check if all available are cooling down
            min_cooldown = min(e.cooldown_until for e in available)
            wait_time = max(0.0, min_cooldown - now)
            raise LLMProviderError(
                f"All Gemini API credentials are currently cooling down. Earliest ready in {wait_time:.1f}s."
            )

    def mark_cooldown(self, key_id: str, cooldown_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            for entry in self._entries:
                if entry.key_id == key_id:
                    entry.cooldown_until = now + cooldown_seconds
                    entry.consecutive_failures += 1
                    logger.warning(
                        "Gemini credential %s entered cooldown for %.1fs (failures: %d)",
                        key_id,
                        cooldown_seconds,
                        entry.consecutive_failures,
                    )
                    break

    def mark_disabled(self, key_id: str) -> None:
        with self._lock:
            for entry in self._entries:
                if entry.key_id == key_id:
                    entry.disabled = True
                    logger.error(
                        "Gemini credential %s disabled permanently due to authentication failure",
                        key_id,
                    )
                    break

    def mark_success(self, key_id: str) -> None:
        with self._lock:
            for entry in self._entries:
                if entry.key_id == key_id:
                    entry.consecutive_failures = 0
                    break


_pool_lock = threading.Lock()
_global_pool: Optional[GeminiKeyPool] = None


def get_pool() -> GeminiKeyPool:
    """Retrieve or lazily initialize the singleton GeminiKeyPool."""
    global _global_pool
    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                keys = parse_api_keys()
                _global_pool = GeminiKeyPool(keys)
    return _global_pool


def set_pool(pool: Optional[GeminiKeyPool]) -> None:
    """Set or reset the global pool (useful for testing)."""
    global _global_pool
    with _pool_lock:
        _global_pool = pool


def generate_content_with_failover(
    contents: Any,
    system_instruction: str,
    response_schema: Optional[Type[Any]] = None,
    temperature: float = 0.0,
    model: Optional[str] = None,
    pool: Optional[GeminiKeyPool] = None,
) -> Any:
    """
    Execute a Gemini generate_content call with robust multi-key failover and
    time-budget constraints.

    Behavior on errors:
    - 429 / RESOURCE_EXHAUSTED: mark key in cooldown, advance to next key, retry
    - 401 / 403 / PERMISSION_DENIED: permanently disable key, advance to next key, retry
    - 400 / INVALID_ARGUMENT: raise LLMProviderError immediately (client error, not fixed by key rotation)
    - 503 / UNAVAILABLE / temporary 5xx / timeout: short cooldown, failover if budget permits
    - Total time budget exceeded: raise LLMProviderError
    """
    model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    target_pool = pool or get_pool()

    req_timeout_sec = float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "8.0"))
    total_budget_sec = float(os.getenv("GEMINI_TOTAL_BUDGET_SECONDS", "25.0"))
    cooldown_sec = float(os.getenv("GEMINI_KEY_COOLDOWN_SECONDS", "60.0"))

    start_time = time.monotonic()
    deadline = start_time + total_budget_sec

    excluded_ids: set[str] = set()
    last_error: Optional[Exception] = None
    all_known_keys = target_pool.all_keys

    while True:
        now = time.monotonic()
        remaining_budget = deadline - now
        if remaining_budget < 1.0:
            raise LLMProviderError(
                f"Gemini call aborted: total time budget of {total_budget_sec:.1f}s exhausted."
            )

        try:
            entry = target_pool.get_candidate(excluded_ids=excluded_ids)
        except LLMProviderError as pool_err:
            clean_msg = _sanitize_message(str(pool_err), all_known_keys)
            raise LLMProviderError(clean_msg) from pool_err

        # Cap the single-request timeout to the remaining total budget
        per_call_timeout = min(req_timeout_sec, remaining_budget)
        http_opts = types.HttpOptions(
            timeout=int(per_call_timeout * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type="application/json" if response_schema else None,
            response_schema=response_schema,
            http_options=http_opts,
        )

        try:
            response = entry.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            target_pool.mark_success(entry.key_id)
            return response

        except errors.APIError as api_err:
            last_error = api_err
            code = getattr(api_err, "code", None)
            status = str(getattr(api_err, "status", "") or "").upper()
            err_msg = str(getattr(api_err, "message", "") or str(api_err))
            sanitized_err = _sanitize_message(err_msg, all_known_keys)

            # 400 Bad Request / Invalid Argument -> do NOT rotate blindly
            if code == 400 or "INVALID_ARGUMENT" in status:
                raise LLMProviderError(
                    f"Gemini rejected request as invalid (HTTP 400): {sanitized_err}"
                ) from api_err

            # 401 / 403 Authentication / Permission -> disable key and advance
            if (
                code in (401, 403)
                or "UNAUTHENTICATED" in status
                or "PERMISSION_DENIED" in status
            ):
                target_pool.mark_disabled(entry.key_id)
                excluded_ids.add(entry.key_id)
                continue

            # 429 Quota / Rate limit exhaustion -> cooldown and advance
            if code == 429 or "RESOURCE_EXHAUSTED" in status:
                target_pool.mark_cooldown(entry.key_id, cooldown_sec)
                excluded_ids.add(entry.key_id)
                continue

            # 503 / 5xx Transient provider / server failure -> short cooldown, retry if budget permits
            if (code and 500 <= code < 600) or "UNAVAILABLE" in status:
                target_pool.mark_cooldown(entry.key_id, min(cooldown_sec, 15.0))
                excluded_ids.add(entry.key_id)
                continue

            # Other 4xx client errors
            if code and 400 <= code < 500:
                raise LLMProviderError(
                    f"Gemini client error (HTTP {code}): {sanitized_err}"
                ) from api_err

            # Fallback for unclassified API errors
            target_pool.mark_cooldown(entry.key_id, min(cooldown_sec, 15.0))
            excluded_ids.add(entry.key_id)
            continue

        except Exception as exc:
            last_error = exc
            err_type = type(exc).__name__
            err_str = str(exc).lower()

            is_timeout_or_net = (
                isinstance(exc, TimeoutError)
                or "timeout" in err_str
                or "timed out" in err_str
                or "connect" in err_str
                or "network" in err_str
                or "socket" in err_str
            )
            if is_timeout_or_net:
                target_pool.mark_cooldown(entry.key_id, min(cooldown_sec, 10.0))
                excluded_ids.add(entry.key_id)
                continue

            sanitized_err = _sanitize_message(str(exc), all_known_keys)
            raise LLMProviderError(
                f"Unexpected failure during Gemini API call: {sanitized_err}"
            ) from exc

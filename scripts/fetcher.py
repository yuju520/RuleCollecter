"""Concurrent download module with retry logic."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

MAX_WORKERS = 5
TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 10


@dataclass
class FetchResult:
    """Result of fetching a single source."""
    name: str
    category: str
    url: str
    success: bool = False
    content: str = ""
    error: str = ""
    rule_count: int = 0


def _is_retryable(status_code: int) -> bool:
    """Check if HTTP status code warrants a retry."""
    return status_code >= 500


def _fetch_one(source: dict) -> FetchResult:
    """Fetch a single source with retry logic."""
    name = source["name"]
    url = source.get("url", "")
    category = source.get("category", "")
    result = FetchResult(name=name, category=category, url=url)

    # Support local file path
    if source.get("path"):
        try:
            with open(source["path"], "r", encoding="utf-8") as f:
                result.content = f.read()
            result.success = True
            logger.info(f"[{name}] Loaded local file: {source['path']}")
        except Exception as e:
            result.error = str(e)
            logger.error(f"[{name}] Failed to load local file: {e}")
        return result

    if not url:
        result.error = "No URL or path configured"
        return result

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code == 200:
                result.content = resp.text
                result.success = True
                logger.info(f"[{name}] Downloaded successfully ({len(resp.text)} bytes)")
                return result

            # Client error (4xx) - don't retry
            if 400 <= resp.status_code < 500:
                result.error = f"HTTP {resp.status_code}"
                logger.error(f"[{name}] Client error {resp.status_code}, not retrying")
                return result

            # Server error (5xx) - retry
            if _is_retryable(resp.status_code):
                logger.warning(
                    f"[{name}] Server error {resp.status_code}, "
                    f"attempt {attempt}/{MAX_RETRIES}"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    result.error = f"HTTP {resp.status_code} after {MAX_RETRIES} retries"

        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(
                f"[{name}] Network error: {e}, attempt {attempt}/{MAX_RETRIES}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                result.error = f"{type(e).__name__} after {MAX_RETRIES} retries"
        except Exception as e:
            result.error = str(e)
            logger.error(f"[{name}] Unexpected error: {e}")
            return result

    return result


def fetch_all(sources: list[dict]) -> list[FetchResult]:
    """Fetch all sources concurrently.

    Args:
        sources: List of source dicts with keys: name, url, category, type, enabled

    Returns:
        List of FetchResult objects.
    """
    enabled = [s for s in sources if s.get("enabled", True)]
    results = []

    logger.info(f"Fetching {len(enabled)} sources with {MAX_WORKERS} workers...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(_fetch_one, s): s for s in enabled}
        for future in as_completed(future_map):
            results.append(future.result())

    success = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    logger.info(f"Fetch complete: {success} success, {failed} failed")

    return results


def fetch_reject_sources(rejects: list[dict]) -> str:
    """Fetch blacklist/reject sources and return combined content."""
    combined = []
    for reject in rejects:
        if not reject.get("enabled", True):
            continue
        result = _fetch_one(reject)
        if result.success:
            combined.append(result.content)
        else:
            logger.warning(f"[Reject:{reject['name']}] Failed: {result.error}")
    return "\n".join(combined)

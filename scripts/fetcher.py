"""Concurrent download module with retry logic."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

MAX_WORKERS = 10
CONNECT_TIMEOUT = 10   # seconds to establish TCP connection
READ_TIMEOUT = 30      # seconds between received chunks (not total)
TOTAL_TIMEOUT = 90     # hard cap on total download time per source
MAX_RETRIES = 2
RETRY_DELAY = 5


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
    return status_code >= 500


def _download_with_total_timeout(url: str) -> str:
    """Download URL content with a hard total-time cap.

    requests timeout= only resets on each received chunk, so a slow-but-steady
    server (e.g. GitHub CDN under load) can hold a connection open for minutes.
    Using stream=True + elapsed tracking enforces a true wall-clock deadline.
    """
    deadline = time.monotonic() + TOTAL_TIMEOUT
    resp = requests.get(
        url,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        stream=True,
    )
    resp.raise_for_status()

    chunks = []
    for chunk in resp.iter_content(chunk_size=65536):
        if time.monotonic() > deadline:
            resp.close()
            raise requests.Timeout(
                f"Total download exceeded {TOTAL_TIMEOUT}s"
            )
        if chunk:
            chunks.append(chunk)

    return b"".join(chunks).decode("utf-8", errors="replace")


def _fetch_one(source: dict) -> FetchResult:
    """Fetch a single source with retry logic."""
    name = source["name"]
    url = source.get("url", "")
    category = source.get("category", "")
    result = FetchResult(name=name, category=category, url=url)

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
            text = _download_with_total_timeout(url)
            result.content = text
            result.success = True
            logger.info(f"[{name}] Downloaded successfully ({len(text)} bytes)")
            return result

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if 400 <= status < 500:
                result.error = f"HTTP {status}"
                logger.error(f"[{name}] Client error {status}, not retrying")
                return result
            logger.warning(f"[{name}] Server error {status}, attempt {attempt}/{MAX_RETRIES}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                result.error = f"HTTP {status} after {MAX_RETRIES} retries"

        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"[{name}] Network error: {e}, attempt {attempt}/{MAX_RETRIES}")
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
    """Fetch all sources concurrently."""
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

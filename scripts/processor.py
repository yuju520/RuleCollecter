"""Merge, dedup, blacklist filtering, and diff module."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from parser import DOMAIN, IPCIDR, parse_rules
from fetcher import FetchResult

logger = logging.getLogger(__name__)

HISTORY_PATH = "rules/history.json"


@dataclass
class CategoryStats:
    """Statistics for a single category."""
    domain_total: int = 0
    domain_unique: int = 0
    ip_total: int = 0
    ip_unique: int = 0
    domain_added: int = 0
    domain_removed: int = 0
    ip_added: int = 0
    ip_removed: int = 0
    changed: bool = False


@dataclass
class ProcessResult:
    """Result of processing all rules."""
    # category -> type -> set of rules
    rules: dict[str, dict[str, set]] = field(default_factory=dict)
    # category -> CategoryStats
    stats: dict[str, CategoryStats] = field(default_factory=dict)
    # source -> {success, rule_count, error}
    source_results: list[FetchResult] = field(default_factory=list)
    # Raw counts before dedup (category -> type -> count)
    raw_counts: dict[str, dict[str, int]] = field(default_factory=dict)


def merge_rules(fetch_results: list[FetchResult], categories: dict) -> ProcessResult:
    """Merge fetched rules by category, dedup within each category.

    Args:
        fetch_results: List of FetchResult from fetcher.
        categories: Category definitions from config.

    Returns:
        ProcessResult with merged and deduped rules.
    """
    result = ProcessResult(source_results=fetch_results)

    # Initialize category rule sets
    for cat_key, cat_info in categories.items():
        result.rules[cat_key] = {DOMAIN: set(), IPCIDR: set()}
        result.raw_counts[cat_key] = {DOMAIN: 0, IPCIDR: 0}

    # Parse and merge
    for fr in fetch_results:
        if not fr.success:
            continue

        cat = fr.category
        if cat not in result.rules:
            logger.warning(f"[{fr.name}] Unknown category '{cat}', skipping")
            continue

        parsed = parse_rules(fr.content, fr.name)
        fr.rule_count = len(parsed[DOMAIN]) + len(parsed[IPCIDR])

        result.raw_counts[cat][DOMAIN] += len(parsed[DOMAIN])
        result.raw_counts[cat][IPCIDR] += len(parsed[IPCIDR])

        result.rules[cat][DOMAIN].update(parsed[DOMAIN])
        result.rules[cat][IPCIDR].update(parsed[IPCIDR])

    return result


def apply_blacklist(process_result: ProcessResult, blacklist_content: str) -> None:
    """Apply blacklist filtering to remove rejected rules in-place.

    The blacklist is parsed through the same parser, so format normalization
    ensures matching (e.g. 'ads.com' becomes 'DOMAIN-SUFFIX,ads.com').
    """
    if not blacklist_content.strip():
        logger.info("No blacklist content to apply")
        return

    parsed = parse_rules(blacklist_content, "blacklist")
    bl_domain = set(parsed[DOMAIN])
    bl_ipcidr = set(parsed[IPCIDR])

    total_removed = 0
    for cat_key, type_rules in process_result.rules.items():
        before_d = len(type_rules[DOMAIN])
        before_i = len(type_rules[IPCIDR])
        type_rules[DOMAIN] -= bl_domain
        type_rules[IPCIDR] -= bl_ipcidr
        removed = (before_d - len(type_rules[DOMAIN])) + (before_i - len(type_rules[IPCIDR]))
        if removed:
            logger.info(f"[{cat_key}] Blacklist removed {removed} rules")
            total_removed += removed

    logger.info(f"Blacklist total removed: {total_removed} rules")


def compute_diff(process_result: ProcessResult) -> None:
    """Compare current rules with history.json and compute stats."""
    history = _load_history()
    old_cats = history.get("categories", {})

    for cat_key, type_rules in process_result.rules.items():
        stats = CategoryStats()
        stats.domain_total = process_result.raw_counts.get(cat_key, {}).get(DOMAIN, 0)
        stats.ip_total = process_result.raw_counts.get(cat_key, {}).get(IPCIDR, 0)
        stats.domain_unique = len(type_rules[DOMAIN])
        stats.ip_unique = len(type_rules[IPCIDR])

        # Diff against history
        old = old_cats.get(cat_key, {})
        old_domain = set(old.get(DOMAIN, []))
        old_ipcidr = set(old.get(IPCIDR, []))

        stats.domain_added = len(type_rules[DOMAIN] - old_domain)
        stats.domain_removed = len(old_domain - type_rules[DOMAIN])
        stats.ip_added = len(type_rules[IPCIDR] - old_ipcidr)
        stats.ip_removed = len(old_ipcidr - type_rules[IPCIDR])

        stats.changed = (
            stats.domain_added > 0 or stats.domain_removed > 0 or
            stats.ip_added > 0 or stats.ip_removed > 0
        )

        process_result.stats[cat_key] = stats


def save_history(process_result: ProcessResult) -> None:
    """Save current rules to history.json."""
    data = {
        "last_update": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }
    for cat_key, type_rules in process_result.rules.items():
        data["categories"][cat_key] = {
            DOMAIN: sorted(type_rules[DOMAIN]),
            IPCIDR: sorted(type_rules[IPCIDR]),
        }

    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"History saved to {HISTORY_PATH}")


def _load_history() -> dict:
    """Load history.json, return empty structure if not found."""
    if not os.path.exists(HISTORY_PATH):
        return {"categories": {}}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load history: {e}")
        return {"categories": {}}

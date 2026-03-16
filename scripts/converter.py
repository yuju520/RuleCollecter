"""Mihomo conversion and file distribution module."""

import logging
import os
import shutil
import subprocess
import tempfile

from parser import DOMAIN, IPCIDR
from processor import ProcessResult

logger = logging.getLogger(__name__)

# Platform output directories
PLATFORMS = {
    "surge": "rules/surge",
    "loon": "rules/loon",
    "egern": "rules/egern",
    "meta": "rules/meta",
}


def write_list_files(process_result: ProcessResult, categories: dict) -> None:
    """Write .list files for Surge/Loon/Egern platforms.

    All three platforms use the same list format, so we write identical files.
    """
    for cat_key, type_rules in process_result.rules.items():
        cat_info = categories.get(cat_key, {})
        output_name = cat_info.get("output_file", cat_key)

        for rule_type in (DOMAIN, IPCIDR):
            rules = type_rules[rule_type]
            if not rules:
                continue

            sorted_rules = sorted(rules)
            content = "\n".join(sorted_rules) + "\n"

            # Write to surge, loon, egern (identical format)
            for platform in ("surge", "loon", "egern"):
                dir_path = f"{PLATFORMS[platform]}/{rule_type}"
                os.makedirs(dir_path, exist_ok=True)
                file_path = f"{dir_path}/{output_name}.list"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                logger.debug(f"Written {file_path} ({len(sorted_rules)} rules)")

    logger.info("List files written for Surge/Loon/Egern")


def _extract_mrs_value(rule: str, rule_type: str) -> str | None:
    """Extract the value part from a rule for MRS format.

    MRS format only accepts raw values without prefixes:
    - Domain MRS: just domain names (one per line)
    - IP MRS: just CIDR notation (one per line)

    Returns None if the rule type is not supported by MRS.
    """
    upper = rule.upper()

    if rule_type == DOMAIN:
        # Domain MRS supports: DOMAIN, DOMAIN-SUFFIX, DOMAIN-KEYWORD
        for prefix in ("DOMAIN,", "DOMAIN-SUFFIX,", "DOMAIN-KEYWORD,"):
            if upper.startswith(prefix):
                value = rule[len(prefix):].strip()
                if value:
                    # For MRS, we need to add prefix indicator
                    # mihomo domain MRS format: +.domain (suffix), full.domain (full match)
                    if upper.startswith("DOMAIN-SUFFIX,"):
                        return f"+.{value}"
                    elif upper.startswith("DOMAIN,"):
                        return value
                    elif upper.startswith("DOMAIN-KEYWORD,"):
                        # MRS doesn't support keyword well, skip
                        return None
        return None

    elif rule_type == IPCIDR:
        # IP MRS supports: IP-CIDR, IP-CIDR6
        for prefix in ("IP-CIDR,", "IP-CIDR6,"):
            if upper.startswith(prefix):
                value = rule[len(prefix):].strip()
                # Remove ",no-resolve" suffix if present
                if "," in value:
                    value = value.split(",")[0]
                if value:
                    return value
        return None

    return None


def convert_to_mrs(process_result: ProcessResult, categories: dict) -> None:
    """Convert rules to MRS format using mihomo.

    MRS format only supports basic domain and CIDR rules.
    Other rule types (IP-ASN, GEOSITE, GEOIP, etc.) are filtered out.
    """
    for cat_key, type_rules in process_result.rules.items():
        cat_info = categories.get(cat_key, {})
        output_name = cat_info.get("output_file", cat_key)

        for rule_type in (DOMAIN, IPCIDR):
            rules = type_rules[rule_type]
            if not rules:
                continue

            # Extract MRS-compatible values
            mrs_values = []
            for rule in rules:
                value = _extract_mrs_value(rule, rule_type)
                if value:
                    mrs_values.append(value)

            mrs_values = sorted(set(mrs_values))  # Dedup and sort

            if not mrs_values:
                logger.info(
                    f"[{cat_key}/{rule_type}] No MRS-compatible rules, skipping"
                )
                continue

            meta_dir = f"{PLATFORMS['meta']}/{rule_type}"
            os.makedirs(meta_dir, exist_ok=True)
            mrs_path = f"{meta_dir}/{output_name}.mrs"

            # Create a temp file with filtered rules for mihomo input
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".list", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write("\n".join(mrs_values) + "\n")
                tmp_path = tmp.name

            try:
                _run_mihomo(rule_type, tmp_path, mrs_path)
                logger.debug(f"Converted {mrs_path} ({len(mrs_values)} rules)")
            except RuntimeError as e:
                logger.warning(f"[{cat_key}/{rule_type}] MRS conversion failed: {e}")
                # Don't raise - continue with other conversions
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    logger.info("MRS conversion complete for Meta")


def _run_mihomo(rule_type: str, input_path: str, output_path: str) -> None:
    """Run mihomo convert-ruleset command."""
    # Support both 'mihomo' (Linux/PATH) and local './mihomo.exe' (Windows)
    mihomo_cmd = "mihomo"
    if os.path.exists("mihomo.exe"):
        mihomo_cmd = "./mihomo.exe"
    elif os.path.exists("mihomo"):
        mihomo_cmd = "./mihomo"

    cmd = [
        mihomo_cmd, "convert-ruleset",
        rule_type,  # "domain" or "ipcidr"
        "text",
        input_path,
        output_path,
    ]
    logger.debug(f"Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"mihomo conversion failed for {input_path}: {error_msg}"
        )

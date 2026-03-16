"""Main entry point for rule collection and processing."""

import logging
import os
import sys

import yaml

# Add scripts directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetcher import fetch_all, fetch_reject_sources
from processor import merge_rules, apply_blacklist, compute_diff, save_history
from converter import write_list_files, convert_to_mrs
from reporter import generate_report, update_readme
from notifier import send_notification

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = "sources.yaml"


def load_config() -> dict:
    """Load and validate sources.yaml configuration."""
    if not os.path.exists(CONFIG_PATH):
        logger.error(f"Configuration file not found: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


def validate_config(config: dict) -> None:
    """Validate that all source categories are defined."""
    categories = config.get("categories", {})
    sources = config.get("sources", [])
    errors = []

    for source in sources:
        cat = source.get("category", "")
        if cat and cat not in categories:
            errors.append(
                f"Source '{source.get('name', '?')}' references "
                f"undefined category '{cat}'"
            )

    if errors:
        for err in errors:
            logger.error(err)
        logger.error("Configuration validation failed. Aborting.")
        sys.exit(1)

    logger.info(
        f"Config validated: {len(categories)} categories, "
        f"{len(sources)} sources"
    )


def main():
    """Main execution flow."""
    logger.info("=" * 60)
    logger.info("Rule Collecter - Starting")
    logger.info("=" * 60)

    # Step 1: Load and validate config
    config = load_config()
    validate_config(config)

    categories = config.get("categories", {})
    sources = config.get("sources", [])
    rejects = config.get("rejects", [])

    run_success = True

    try:
        # Step 2: Fetch all rule sources
        logger.info("Step 1: Fetching rule sources...")
        fetch_results = fetch_all(sources)

        # Step 3: Fetch blacklist sources
        logger.info("Step 2: Fetching blacklist sources...")
        blacklist_content = fetch_reject_sources(rejects)

        # Step 4: Merge and dedup rules by category
        logger.info("Step 3: Merging and deduplicating rules...")
        process_result = merge_rules(fetch_results, categories)

        # Step 5: Apply blacklist filtering
        logger.info("Step 4: Applying blacklist filtering...")
        apply_blacklist(process_result, blacklist_content)

        # Step 6: Compute diff against history
        logger.info("Step 5: Computing changes...")
        compute_diff(process_result)

        # Step 7: Write list files (Surge/Loon/Egern)
        logger.info("Step 6: Writing list files...")
        write_list_files(process_result, categories)

        # Step 8: Convert to MRS (Meta)
        logger.info("Step 7: Converting to MRS format...")
        convert_to_mrs(process_result, categories)

        # Step 9: Save history (only after successful conversion)
        logger.info("Step 8: Saving history...")
        save_history(process_result)

        # Step 10: Generate report
        logger.info("Step 9: Generating report...")
        generate_report(process_result, categories, success=True)

        # Step 11: Update README
        logger.info("Step 10: Updating README...")
        update_readme(process_result, categories)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        run_success = False

        # Still try to generate a failure report
        try:
            if 'process_result' in locals():
                generate_report(process_result, categories, success=False)
        except Exception:
            logger.error("Failed to generate error report")

    # Step 12: Send Telegram notification
    logger.info("Step 11: Sending notification...")
    try:
        if 'process_result' in locals():
            send_notification(process_result, categories, success=run_success)
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

    if run_success:
        logger.info("=" * 60)
        logger.info("Rule Collecter - Completed successfully")
        logger.info("=" * 60)
    else:
        logger.error("Rule Collecter - Completed with errors")
        sys.exit(1)


if __name__ == "__main__":
    main()

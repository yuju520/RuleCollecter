"""Telegram notification module."""

import logging
import os

import requests

logger = logging.getLogger(__name__)


def send_notification(
    process_result,
    categories: dict,
    success: bool = True,
) -> None:
    """Send update notification via Telegram bot.

    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials not configured, skipping notification")
        return

    from parser import DOMAIN, IPCIDR
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    status = "✅ 成功" if success else "❌ 失败"

    total_domain = sum(s.domain_unique for s in process_result.stats.values())
    total_ip = sum(s.ip_unique for s in process_result.stats.values())
    total_sources = len(process_result.source_results)
    success_count = sum(1 for r in process_result.source_results if r.success)

    failed = [r for r in process_result.source_results if not r.success]
    failed_names = ", ".join(r.name for r in failed) if failed else "无"

    # Build report URL
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    if repo:
        report_url = f"https://github.com/{repo}/blob/{branch}/reports/update-report.md"
    else:
        report_url = "N/A"

    text = (
        f"🔔 规则更新通知\n\n"
        f"⏰ 时间：{now}\n"
        f"📊 状态：{status}\n\n"
        f"📈 统计：\n"
        f"• 🌐 域名规则：{total_domain} 条\n"
        f"• 🔢 IP规则：{total_ip} 条\n"
        f"• ✅ 成功源：{success_count}/{total_sources}\n\n"
        f"❌ 失败：{failed_names}\n\n"
        f"📄 详细报告：{report_url}"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("Telegram notification sent successfully")
        else:
            logger.error(f"Telegram API error: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")

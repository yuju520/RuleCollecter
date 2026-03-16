"""Report generation module."""

import logging
import os
import re
from datetime import datetime, timezone, timedelta

from parser import DOMAIN, IPCIDR
from processor import ProcessResult

logger = logging.getLogger(__name__)

REPORT_PATH = "reports/update-report.md"
README_PATH = "README.md"

# Beijing timezone
TZ_BEIJING = timezone(timedelta(hours=8))


def generate_report(
    process_result: ProcessResult,
    categories: dict,
    success: bool = True,
) -> str:
    """Generate Markdown update report.

    Returns:
        The report content string.
    """
    now = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    status = "✅ 成功" if success else "❌ 失败"

    total_sources = len(process_result.source_results)
    success_count = sum(1 for r in process_result.source_results if r.success)
    failed_count = total_sources - success_count

    # Aggregate stats
    total_domain = sum(s.domain_unique for s in process_result.stats.values())
    total_ip = sum(s.ip_unique for s in process_result.stats.values())
    raw_domain = sum(s.domain_total for s in process_result.stats.values())
    raw_ip = sum(s.ip_total for s in process_result.stats.values())
    total_cats = len(process_result.stats)
    changed_cats = sum(1 for s in process_result.stats.values() if s.changed)

    lines = []
    lines.append("# 🔄 规则更新报告\n")
    lines.append(f"**⏰ 更新时间：** `{now}`  ")
    lines.append(f"**📊 运行状态：** `{status}`\n")
    lines.append("\n---\n")

    # Overall stats
    lines.append("## 📈 总体统计\n")
    lines.append("| 指标 | 数量 |")
    lines.append("|:-----|-----:|")
    lines.append(f"| 规则源总数 | `{total_sources}` |")
    lines.append(f"| ✅ 成功获取 | `{success_count}` |")
    lines.append(f"| ❌ 失败获取 | `{failed_count}` |")
    lines.append(f"| 📂 处理分类数 | `{total_cats}` |")
    lines.append(f"| 🔄 变化分类数 | `{changed_cats}` |\n")

    lines.append("### 规则数量统计\n")
    lines.append("| 规则类型 | 原始总数 | 去重后数量 |")
    lines.append("|:---------|--------:|----------:|")
    lines.append(f"| 🌐 域名规则 | `{raw_domain}` | `{total_domain}` |")
    lines.append(f"| 🔢 IP规则 | `{raw_ip}` | `{total_ip}` |\n")

    # Changes table
    lines.append("---\n")
    lines.append("## 🆕 本次更新变化\n")
    lines.append("| 分类 | 🌐 域名规则 | 🔢 IP规则 |")
    lines.append("|:-----|-----------:|----------:|")
    for cat_key in sorted(process_result.stats.keys()):
        s = process_result.stats[cat_key]
        cat_name = categories.get(cat_key, {}).get("name", cat_key)
        lines.append(
            f"| {cat_name} | **+{s.domain_added} -{s.domain_removed}** "
            f"| **+{s.ip_added} -{s.ip_removed}** |"
        )
    lines.append("")

    # Category details
    lines.append("---\n")
    lines.append("## 📂 分类详情与文件下载\n")
    for cat_key in sorted(categories.keys()):
        cat_info = categories[cat_key]
        cat_name = cat_info.get("name", cat_key)
        output = cat_info.get("output_file", cat_key)
        stats = process_result.stats.get(cat_key)
        if not stats:
            continue

        lines.append(f"### 🏷️ {cat_name}\n")
        lines.append("**📦 输出文件总览：**\n")
        lines.append("| 平台 | 格式 | 🌐 域名规则 (点击下载) | 🔢 IP规则 (点击下载) |")
        lines.append("|:-----|:-----|:----- |:----- |")

        d_count = stats.domain_unique
        i_count = stats.ip_unique
        d_link = f"[📥 `{output}.mrs`](rules/meta/domain/{output}.mrs)" if d_count else "-"
        i_link = f"[📥 `{output}.mrs`](rules/meta/ipcidr/{output}.mrs)" if i_count else "-"
        lines.append(f"| **Meta** | `.mrs` | {d_link} ({d_count}) | {i_link} ({i_count}) |")

        for plat in ("Surge", "Loon", "Egern"):
            plat_lower = plat.lower()
            d_link = f"[📥 `{output}.list`](rules/{plat_lower}/domain/{output}.list)" if d_count else "-"
            i_link = f"[📥 `{output}.list`](rules/{plat_lower}/ipcidr/{output}.list)" if i_count else "-"
            lines.append(f"| **{plat}** | `.list` | {d_link} ({d_count}) | {i_link} ({i_count}) |")

        lines.append("")

        # Source status for this category
        cat_sources = [
            r for r in process_result.source_results if r.category == cat_key
        ]
        if cat_sources:
            lines.append("**📥 规则源状态：**\n")
            lines.append("| 源名称 | 状态 | 获取规则数 |")
            lines.append("|:-------|:-----|----------:|")
            for sr in cat_sources:
                st = "✅" if sr.success else "❌"
                lines.append(f"| {sr.name} | {st} | {sr.rule_count} |")
            lines.append("")

    # Failed list
    failed = [r for r in process_result.source_results if not r.success]
    if failed:
        lines.append("---\n")
        lines.append("## ❌ 失败列表\n")
        lines.append("| 源名称 | 错误信息 |")
        lines.append("|:-------|:---------|")
        for r in failed:
            lines.append(f"| {r.name} | {r.error} |")
        lines.append("")

    lines.append("---\n")

    report = "\n".join(lines)

    # Write report file
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Report saved to {REPORT_PATH}")

    return report


def update_readme(process_result: ProcessResult, categories: dict) -> None:
    """Update README.md with rules statistics between marker comments."""
    now = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("<!-- RULES_STATS_START -->")
    lines.append("## 📈 规则统计\n")
    lines.append(f"**🕒 更新时间：** `{now}`\n")
    lines.append("| 分类 | Meta (MRS) | Surge/Loon/Egern (List) |")
    lines.append("|:-----|----------:|-----------------------:|")

    for cat_key in sorted(categories.keys()):
        cat_info = categories[cat_key]
        cat_name = cat_info.get("name", cat_key)
        output = cat_info.get("output_file", cat_key)
        stats = process_result.stats.get(cat_key)
        if not stats:
            continue

        # Show domain and ipcidr rows
        for rule_type, count in [(DOMAIN, stats.domain_unique), (IPCIDR, stats.ip_unique)]:
            if count == 0:
                continue
            type_label = f"{cat_name}/{rule_type}"
            mrs_link = f"[📥 Download](rules/meta/{rule_type}/{output}.mrs)"
            list_link = f"[📥 Download](rules/surge/{rule_type}/{output}.list)"
            lines.append(
                f"| {type_label} | {mrs_link} ({count}) | {list_link} ({count}) |"
            )

    lines.append("<!-- RULES_STATS_END -->")
    new_section = "\n".join(lines)

    # Read existing README
    if not os.path.exists(README_PATH):
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(f"# RuleCollecter\n\n---\n{new_section}\n")
        logger.info("Created README.md with stats")
        return

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace between markers
    pattern = r"<!-- RULES_STATS_START -->.*?<!-- RULES_STATS_END -->"
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, new_section, content, flags=re.DOTALL)
    else:
        content = content.rstrip() + f"\n\n---\n{new_section}\n"

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("README.md updated with stats")
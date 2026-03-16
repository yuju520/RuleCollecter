"""Rule parsing and type identification module."""

import re
import logging

logger = logging.getLogger(__name__)

# Rule type constants
DOMAIN = "domain"
IPCIDR = "ipcidr"

# Patterns for domain rules (order matters - check prefixed first)
DOMAIN_PREFIXES = (
    "DOMAIN,", "DOMAIN-SUFFIX,", "DOMAIN-KEYWORD,",
    "DOMAIN-WILDCARD,", "DOMAIN-REGEX,", "GEOSITE,",
)

# Patterns for IP rules
IP_PREFIXES = (
    "IP-CIDR,", "IP-CIDR6,", "IP-SUFFIX,", "IP-ASN,",
)

# Regex for bare domain: e.g. example.com, sub.example.com
RE_BARE_DOMAIN = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
)

# Regex for .example.com or *.example.com (suffix shorthand)
RE_DOT_DOMAIN = re.compile(
    r'^[.*]+([a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,})$'
)

# Regex for bare IPv4 CIDR: e.g. 1.2.3.4/32
RE_IPV4_CIDR = re.compile(
    r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$'
)

# Regex for bare IPv6 CIDR: e.g. 2001:db8::/32
RE_IPV6_CIDR = re.compile(
    r'^[0-9a-fA-F:]+/\d{1,3}$'
)


def parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single rule line and return (type, normalized_rule) or None.

    Returns:
        tuple of (DOMAIN|IPCIDR, normalized_rule_string) or None if unparseable.
    """
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith('#') or line.startswith(';') or line.startswith('//'):
        return None

    # Remove trailing comments (e.g. "DOMAIN,example.com // comment")
    for comment_marker in (' //', ' #'):
        idx = line.find(comment_marker)
        if idx > 0:
            line = line[:idx].strip()

    # Some rules have extra fields after the value (e.g. "DOMAIN,example.com,no-resolve")
    # We need to handle the standard format: TYPE,VALUE[,extra...]
    upper_line = line.upper()

    # Check domain prefixes
    for prefix in DOMAIN_PREFIXES:
        if upper_line.startswith(prefix):
            # Extract the value part (keep original case for the value)
            rest = line[len(prefix):]
            # Remove extra parameters like ",no-resolve"
            value = rest.split(',')[0].strip()
            if value:
                return (DOMAIN, f"{prefix.rstrip(',')},{value}")
            return None

    # Check IP prefixes
    for prefix in IP_PREFIXES:
        if upper_line.startswith(prefix):
            rest = line[len(prefix):]
            value = rest.split(',')[0].strip()
            if value:
                return (IPCIDR, f"{prefix.rstrip(',')},{value}")
            return None

    # Check for .example.com or *.example.com → DOMAIN-SUFFIX
    if line.startswith('.') or line.startswith('*.'):
        m = RE_DOT_DOMAIN.match(line)
        if m:
            domain = m.group(1)
            return (DOMAIN, f"DOMAIN-SUFFIX,{domain}")

    # Check for bare IPv4 CIDR
    if RE_IPV4_CIDR.match(line):
        return (IPCIDR, f"IP-CIDR,{line}")

    # Check for bare IPv6 CIDR (must contain ':')
    if ':' in line and RE_IPV6_CIDR.match(line):
        return (IPCIDR, f"IP-CIDR6,{line}")

    # Check for bare domain
    if RE_BARE_DOMAIN.match(line):
        return (DOMAIN, f"DOMAIN-SUFFIX,{line}")

    # Unrecognized line
    return None


def parse_rules(content: str, source_name: str = "") -> dict[str, list[str]]:
    """Parse rule content and return categorized rules.

    Returns:
        dict with keys 'domain' and 'ipcidr', each containing a list of normalized rules.
    """
    result = {DOMAIN: [], IPCIDR: []}

    for line_num, line in enumerate(content.splitlines(), 1):
        try:
            parsed = parse_line(line)
            if parsed:
                rule_type, rule = parsed
                result[rule_type].append(rule)
        except Exception as e:
            logger.warning(f"[{source_name}] Failed to parse line {line_num}: {line!r} - {e}")

    return result

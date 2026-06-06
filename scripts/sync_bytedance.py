"""
Sync ByteDance domain list from v2fly/domain-list-community.

Usage:
    python scripts/sync_bytedance.py

Fetches bytedance.txt and all referenced include files from the upstream
v2fly/domain-list-community repository, cleans the domains, and writes
them to lists/bytedance_blocklist.txt.
"""

import re
import os
import http.client
import ssl

REPO_RAW = "raw.githubusercontent.com"
REPO_PATH = "/v2fly/domain-list-community/master/data"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "lists", "bytedance_blocklist.txt")
ENTRY_POINT = "bytedance"

# Regex to extract a valid domain from a line
DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    r"(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*$"
)


def fetch_file(name: str) -> str:
    """Fetch a domain list file from the v2fly repo."""
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(REPO_RAW, context=ctx, timeout=15)
    try:
        url = f"{REPO_PATH}/{name}"
        conn.request("GET", url)
        resp = conn.getresponse()
        if resp.status != 200:
            print(f"  [WARN] Failed to fetch {name}: HTTP {resp.status}")
            return ""
        return resp.read().decode("utf-8")
    finally:
        conn.close()


def parse_and_resolve(name: str, visited: set[str], all_domains: set[str], section_label: str) -> str:
    """
    Recursively parse a v2fly domain list file.
    Resolves include: directives and collects clean domains.
    Returns a section label for the top-level caller.
    """
    if name in visited:
        return ""
    visited.add(name)

    content = fetch_file(name)
    if not content:
        return ""

    includes = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Handle include directives
        if stripped.startswith("include:"):
            inc_name = stripped.split("include:")[1].split("#")[0].strip()
            includes.append(inc_name)
            continue

        # Clean the line: strip tags (@!cn, @ads, etc.) and full: prefix
        cleaned = stripped.split("#")[0].strip()  # remove inline comments
        cleaned = re.sub(r"\s+@\S+", "", cleaned).strip()  # remove @tags
        if cleaned.startswith("full:"):
            cleaned = cleaned[5:]

        # Validate as domain
        if DOMAIN_RE.match(cleaned):
            all_domains.add(cleaned.lower())

    # Recursively resolve includes
    for inc in includes:
        parse_and_resolve(inc, visited, all_domains, inc)

    return section_label


def main():
    print(f"Fetching ByteDance domain list from {REPO_RAW}{REPO_PATH}...")

    all_domains: set[str] = set()
    visited: set[str] = set()

    parse_and_resolve(ENTRY_POINT, visited, all_domains, ENTRY_POINT)

    # Sort domains
    sorted_domains = sorted(all_domains)

    print(f"Resolved {len(visited)} files, collected {len(sorted_domains)} unique domains.")

    # Write output
    output_path = os.path.abspath(OUTPUT_FILE)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# ========================================\n")
        f.write("# ByteDance 全域名封锁列表\n")
        f.write("# 自动生成 - 请勿手动编辑\n")
        f.write(f"# 来源: https://github.com/v2fly/domain-list-community\n")
        f.write(f"# 解析文件数: {len(visited)}\n")
        f.write(f"# 域名总数: {len(sorted_domains)}\n")
        f.write("# ========================================\n\n")
        for domain in sorted_domains:
            f.write(f"{domain}\n")

    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()

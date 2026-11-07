"""
Sync ByteDance ad/tracking domain list from v2fly/domain-list-community.

Usage:
    python scripts/sync_bytedance.py

Fetches bytedance.txt and all referenced include files from the upstream
v2fly/domain-list-community repository, keeps only entries tagged @ads or
@telemetry (advertising/tracking), and writes them to
lists/bytedance_blocklist.txt.
"""

import re
import os
import sys
import time
import http.client
import ssl

REPO_RAW = "raw.githubusercontent.com"
REPO_PATH = "/v2fly/domain-list-community/master/data"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "lists", "bytedance_blocklist.txt")
ENTRY_POINT = "bytedance"

# Only keep domains upstream marks as advertising or telemetry/tracking.
AD_TAGS = {"@ads", "@telemetry"}

# Regex to extract a valid domain from a line
DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    r"(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*$"
)


class FetchError(Exception):
    pass


def fetch_file(name: str) -> str:
    """Fetch a domain list file from the v2fly repo, retrying transient errors."""
    last_error = None
    for attempt in range(1, 4):
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(REPO_RAW, context=ctx, timeout=20)
        try:
            url = f"{REPO_PATH}/{name}"
            conn.request("GET", url, headers={"User-Agent": "Mozilla/5.0"})
            resp = conn.getresponse()
            if resp.status != 200:
                raise FetchError(f"HTTP {resp.status} for {name}")
            return resp.read().decode("utf-8")
        except (OSError, ssl.SSLError, http.client.HTTPException, FetchError) as exc:
            last_error = exc
            print(f"  [WARN] Failed to fetch {name} (attempt {attempt}/3): {exc}")
            time.sleep(2 * attempt)
        finally:
            conn.close()
    raise FetchError(f"Failed to fetch {name}: {last_error}")


def count_domains(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as file:
        return sum(1 for line in file if line.strip() and not line.startswith("#"))


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
        body = stripped.split("#")[0].strip()  # remove inline comments
        tags = set(re.findall(r"@[!a-zA-Z0-9-]+", body))
        cleaned = re.sub(r"\s+@\S+", "", body).strip()  # remove @tags
        if cleaned.startswith("full:"):
            cleaned = cleaned[5:]

        # Keep only ad/tracking entries and validate as domain
        if AD_TAGS & tags and DOMAIN_RE.match(cleaned):
            all_domains.add(cleaned.lower())

    # Recursively resolve includes
    for inc in includes:
        parse_and_resolve(inc, visited, all_domains, inc)

    return section_label


def main():
    print(f"Fetching ByteDance domain list from {REPO_RAW}{REPO_PATH}...")

    all_domains: set[str] = set()
    visited: set[str] = set()

    try:
        parse_and_resolve(ENTRY_POINT, visited, all_domains, ENTRY_POINT)
    except FetchError as exc:
        print(f"[ERROR] {exc}")
        print("[ERROR] Aborting; existing blocklist left unchanged.")
        sys.exit(1)

    # Sort domains
    sorted_domains = sorted(all_domains)

    print(f"Resolved {len(visited)} files, collected {len(sorted_domains)} ad/tracking domains.")

    output_path = os.path.abspath(OUTPUT_FILE)
    previous_count = count_domains(output_path)

    if not sorted_domains:
        print("[ERROR] No ad/tracking domains collected; aborting.")
        sys.exit(1)
    if previous_count and len(sorted_domains) < previous_count * 0.5:
        print(
            f"[ERROR] Domain count dropped from {previous_count} to "
            f"{len(sorted_domains)}; aborting to avoid wiping the blocklist."
        )
        sys.exit(1)

    # Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# ========================================\n")
        f.write("# ByteDance 广告/追踪域名封锁列表\n")
        f.write("# 自动生成 - 请勿手动编辑\n")
        f.write(f"# 来源: https://github.com/v2fly/domain-list-community\n")
        f.write(f"# 筛选: 仅保留上游标记 @ads / @telemetry 的域名\n")
        f.write(f"# 解析文件数: {len(visited)}\n")
        f.write(f"# 域名总数: {len(sorted_domains)}\n")
        f.write("# ========================================\n\n")
        for domain in sorted_domains:
            f.write(f"{domain}\n")

    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()

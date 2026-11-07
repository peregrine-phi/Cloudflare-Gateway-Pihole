from src import (
    info,
    ip_pattern, 
    domain_pattern, 
    replace_pattern
)

def convert_to_domain_list(block_content: str, white_content: str) -> tuple[list[str], list[str]]:
    white_domains = set()
    block_domains = set()

    # Whitelist sources may express allowances as @@ exception rules.
    extract_domains(white_content, white_domains, include_exceptions=True)

    # @@ rules inside block sources are exceptions: never block them, and
    # carry them into the allow list so a blocked parent cannot override them.
    exception_domains = set()
    extract_exception_domains(block_content, exception_domains)
    white_domains |= exception_domains
    info(f"Number of whitelisted domains: {len(white_domains)}")

    # In block sources, @@ rules are exceptions and must never be blocked.
    extract_domains(block_content, block_domains, include_exceptions=False)
    block_domains = remove_subdomains_if_higher(block_domains)
    info(f"Number of blocked domains: {len(block_domains)}")

    final_domains = sorted(list(block_domains - white_domains))
    info(f"Number of final domains: {len(final_domains)}")

    return final_domains, sorted(white_domains)

def extract_domains(content: str, domains: set[str], include_exceptions: bool = False) -> None:
    for line in content.splitlines():
        _add_domain_line(line, domains, include_exceptions)

def extract_exception_domains(content: str, domains: set[str]) -> None:
    for line in content.splitlines():
        if line.startswith("@@"):
            _add_domain_line(line, domains, include_exceptions=True)

_LOCAL_BLOCK_IPS = ("127.0.0.1", "0.0.0.0")


def _add_domain_line(line: str, domains: set[str], include_exceptions: bool) -> None:
    line = line.strip()
    if line.startswith(("#", "!", "/")) or line == "":
        return

    # Hosts-file entries are only valid for local blocking addresses.
    # Skip entries mapped to real IPs, e.g. "110.43.121.13 bigota.d.miui.com".
    parts = line.split()
    if len(parts) >= 2 and ip_pattern.match(parts[0]):
        if parts[0] not in _LOCAL_BLOCK_IPS:
            return

    if line.startswith("@@"):
        if not include_exceptions:
            return
        line = line[2:]

    cleaned_line = line.lower().split("#")[0].split("^")[0].replace("\r", "")
    domain = replace_pattern.sub("", cleaned_line, count=1)

    # Strip a residual wildcard, e.g. "*.adtech.de" or "||*.foo.com".
    if domain.startswith("*."):
        domain = domain[2:]

    # Single-label names (localhost, broadcasthost, ...) are not internet domains.
    if "." not in domain:
        return

    try:
        domain = domain.encode("idna").decode("utf-8", "replace")
    except UnicodeError:
        return

    if domain_pattern.match(domain) and not ip_pattern.match(domain):
        domains.add(domain)
            
def remove_subdomains_if_higher(domains: set[str]) -> set[str]:
    top_level_domains = set()
    
    for domain in domains:
        parts = domain.split(".")
            
        is_lower_subdomain = False            
        for i in range(1, len(parts)):
            higher_domain = ".".join(parts[i:])
            if higher_domain in domains:
                is_lower_subdomain = True
                break
                    
        if not is_lower_subdomain:
            top_level_domains.add(domain)
                
    return top_level_domains

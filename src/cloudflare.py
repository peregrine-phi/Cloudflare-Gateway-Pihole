import json
from src.requests import (
    cloudflare_gateway_request, retry, rate_limited_request, retry_config
)


@retry(**retry_config)
@rate_limited_request
def create_list(name, domains):
    endpoint = "/lists"
    data = {
        "name": name,
        "description": "Ads & Tracking Domains",
        "type": "DOMAIN",
        "items": [{"value": domain} for domain in domains]
    }
    status, response = cloudflare_gateway_request("POST", endpoint, body=json.dumps(data))
    return response["result"]

@retry(**retry_config)
@rate_limited_request
def update_list(list_id, remove_items, append_items):
    endpoint = f"/lists/{list_id}"    
    data = {
        "remove": [domain for domain in remove_items],
        "append": [{"value": domain} for domain in append_items]
    }    
    status, response = cloudflare_gateway_request("PATCH", endpoint, body=json.dumps(data))
    return response["result"]

@retry(**retry_config)
def create_rule(rule_name, traffic, priority=1000, action="block"):
    endpoint = "/rules"
    data = {
        "name": rule_name,
        "description": "Block Ads & Tracking" if action == "block" else "Allow Exceptions",
        "action": action,
        "precedence": priority,
        "traffic": traffic,
        "enabled": True,
    }
    status, response = cloudflare_gateway_request("POST", endpoint, body=json.dumps(data))
    return response["result"]

@retry(**retry_config)
def update_rule(rule_name, rule_id, traffic, priority=1000, action="block"):
    endpoint = f"/rules/{rule_id}"
    data = {
        "name": rule_name,
        "description": "Block Ads & Tracking" if action == "block" else "Allow Exceptions",
        "action": action,
        "precedence": priority,
        "traffic": traffic,
        "enabled": True,
    }
    status, response = cloudflare_gateway_request("PUT", endpoint, body=json.dumps(data))
    return response["result"]


def get_paginated(endpoint):
    results = []
    page = 1
    previous_first_id = None
    while True:
        separator = "&" if "?" in endpoint else "?"
        status, response = cloudflare_gateway_request(
            "GET", f"{endpoint}{separator}page={page}&per_page=1000"
        )
        batch = response.get("result") or []
        if not batch:
            break

        # Guard against APIs that ignore the page parameter and repeat results.
        first_id = batch[0].get("id")
        if first_id is not None and first_id == previous_first_id:
            break
        previous_first_id = first_id
        results.extend(batch)

        result_info = response.get("result_info") or {}
        if not result_info:
            break
        total = result_info.get("total_count")
        if total is not None:
            if len(results) >= total:
                break
        elif "page" in result_info and "per_page" in result_info:
            if len(batch) < result_info["per_page"]:
                break
        else:
            break
        if page >= 1000:
            break
        page += 1
    return results


@retry(**retry_config)
def get_lists(prefix_name):
    lists = get_paginated("/lists")
    return [l for l in lists if l["name"].startswith(prefix_name)]

@retry(**retry_config)
def get_rules(rule_name_prefix):
    rules = get_paginated("/rules")
    return [r for r in rules if r["name"].startswith(rule_name_prefix)]

@retry(**retry_config)
@rate_limited_request
def delete_list(list_id):
    endpoint = f"/lists/{list_id}"
    status, response = cloudflare_gateway_request("DELETE", endpoint)
    return response["result"]

@retry(**retry_config)
def delete_rule(rule_id):
    endpoint = f"/rules/{rule_id}"
    status, response = cloudflare_gateway_request("DELETE", endpoint)
    return response["result"]

@retry(**retry_config)
def get_list_items(list_id):
    items = []
    cursor = None
    seen_cursors = set()
    while True:
        endpoint = f"/lists/{list_id}/items?limit=1000"
        if cursor:
            endpoint += f"&cursor={cursor}"
        status, response = cloudflare_gateway_request("GET", endpoint)
        batch = response["result"] or []
        items.extend(i["value"] for i in batch)
        cursor = ((response.get("result_info") or {}).get("cursors") or {}).get("after")
        if not batch or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    return items

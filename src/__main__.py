import os
import argparse
from src.domains import DomainConverter
from src import utils, info, silent_error, error, PREFIX
from src.cloudflare import (
    create_list, update_list, create_rule, 
    update_rule, delete_list, delete_rule, get_rules
)
from src.requests import NotFoundException, HTTPException

# Cloudflare Gateway limits (override via environment variables when your plan differs).
MAX_GATEWAY_DOMAINS = int(os.getenv("MAX_GATEWAY_DOMAINS", "300000"))
MAX_GATEWAY_LISTS = int(os.getenv("MAX_GATEWAY_LISTS", "100"))
LIST_CAPACITY = int(os.getenv("GATEWAY_LIST_CAPACITY", "1000"))
ALLOW_RULE_CHUNK = int(os.getenv("ALLOW_RULE_CHUNK", "2000"))
BLOCK_PRECEDENCE = 1000
ALLOW_PRECEDENCE = 900


class CloudflareManager:
    def __init__(self, prefix):
        self.list_name = f"[{prefix}]"
        self.rule_name = f"[{prefix}] Block Ads"
        self.allow_rule_prefix = f"[{prefix}] Allow"
        self.cache = utils.load_cache()

    @staticmethod
    def _list_traffic(list_ids):
        return " or ".join(f"any(dns.domains[*] in ${lst})" for lst in list_ids)

    @staticmethod
    def _check_limits(domains):
        if len(domains) > MAX_GATEWAY_DOMAINS:
            error(
                f"Blocklist has {len(domains)} domains, exceeding the configured "
                f"limit of {MAX_GATEWAY_DOMAINS} (MAX_GATEWAY_DOMAINS)."
            )

        required_lists = (len(domains) + LIST_CAPACITY - 1) // LIST_CAPACITY
        if required_lists > MAX_GATEWAY_LISTS:
            error(
                f"Blocklist needs {required_lists} Gateway lists "
                f"({len(domains)} domains / {LIST_CAPACITY} per list), but only "
                f"{MAX_GATEWAY_LISTS} lists are allowed (MAX_GATEWAY_LISTS). "
                f"Reduce ADLIST_URLS or raise the limit if your plan supports more."
            )

    def _sync_allow_rules(self, domains):
        existing = {rule["name"]: rule for rule in get_rules(self.allow_rule_prefix)}
        desired_names = set()
        chunks = [
            domains[i:i + ALLOW_RULE_CHUNK]
            for i in range(0, len(domains), ALLOW_RULE_CHUNK)
        ]

        for index, chunk in enumerate(chunks, start=1):
            name = f"{self.allow_rule_prefix} - {index:03d}"
            desired_names.add(name)
            traffic = "any(dns.domains[*] in {" + " ".join(f'"{d}"' for d in chunk) + "})"
            rule = existing.get(name)

            if rule is None:
                create_rule(name, traffic, ALLOW_PRECEDENCE + index, action="allow")
                info(f"Created allow rule: {name} ({len(chunk)} domains)")
            elif rule.get("traffic") != traffic:
                try:
                    update_rule(
                        name, rule["id"], traffic, ALLOW_PRECEDENCE + index, action="allow"
                    )
                    info(f"Updated allow rule: {name} ({len(chunk)} domains)")
                except NotFoundException:
                    create_rule(name, traffic, ALLOW_PRECEDENCE + index, action="allow")
                    info(f"Recreated allow rule: {name} ({len(chunk)} domains)")

        for name, rule in existing.items():
            if name not in desired_names:
                try:
                    delete_rule(rule["id"])
                    info(f"Deleted stale allow rule: {name}")
                except NotFoundException:
                    info(f"Stale allow rule already gone: {name}")

    def update_resources(self):
        converter = DomainConverter()
        domains_to_block = converter.process_urls()
        self._check_limits(domains_to_block)
        
        current_lists = utils.get_current_lists(self.cache, self.list_name)
        current_rules = utils.get_current_rules(self.cache, self.rule_name)

        needed_lists = (len(domains_to_block) + LIST_CAPACITY - 1) // LIST_CAPACITY

        # Lists beyond the current requirement must be removed, but Cloudflare
        # refuses to delete a list still referenced by a policy. Keep their IDs,
        # detach them from the block rule first, and delete them afterwards.
        surplus_lists = []
        kept_lists = []
        for lst in current_lists:
            try:
                index = int(lst["name"].split("-")[-1])
            except ValueError:
                kept_lists.append(lst)
                continue
            if index > needed_lists:
                surplus_lists.append(lst)
            else:
                kept_lists.append(lst)

        for lst in surplus_lists:
            self.cache["lists"] = [
                item for item in self.cache["lists"] if item["id"] != lst["id"]
            ]
            self.cache["mapping"].pop(lst["id"], None)
        current_lists = kept_lists

        # Mapping list_id to current domains in that list
        list_id_to_domains = {}
        for lst in current_lists:
            items = utils.get_list_items_cached(self.cache, lst["id"])
            if items is None:
                info(f"Skipping stale list: {lst['name']} (not found on Cloudflare)")
                continue
            list_id_to_domains[lst["id"]] = set(items)

        # Refresh current_lists after possible stale list removal
        current_lists = self.cache["lists"]

        # Mapping domain to its current list_id
        domain_to_list_id = {domain: lst_id for lst_id, domains in list_id_to_domains.items() for domain in domains}

        # Calculate remaining domains 
        remaining_domains = set(domains_to_block) - set(domain_to_list_id.keys())

        # Create a dictionary for list names to keep track of missing indexes
        list_name_to_id = {lst["name"]: lst["id"] for lst in current_lists}
        existing_indexes = []
        for name in list_name_to_id:
            try:
                existing_indexes.append(int(name.split("-")[-1]))
            except ValueError:
                continue
        existing_indexes.sort()

        # Determine the needed indexes
        all_indexes = set(range(1, max(existing_indexes + [needed_lists]) + 1))
        
        # Process current lists and fill them with remaining domains
        new_list_ids = []
        for i in all_indexes:
            list_name = f"{self.list_name} - {i:03d}"
            if list_name in list_name_to_id:
                list_id = list_name_to_id[list_name]
                current_values = list_id_to_domains[list_id]
                remove_items = current_values - set(domains_to_block)
                chunk = current_values - remove_items

                new_items = []
                if len(chunk) < LIST_CAPACITY:
                    needed_items = LIST_CAPACITY - len(chunk)
                    new_items = list(remaining_domains)[:needed_items]
                    chunk.update(new_items)
                    remaining_domains.difference_update(new_items)

                if remove_items or new_items:
                    try:
                        update_list(list_id, remove_items, new_items)
                    except NotFoundException:
                        info(f"List {list_name} no longer exists on Cloudflare, recreating...")
                        new_items_full = list(chunk)
                        available = LIST_CAPACITY - len(new_items_full)
                        if available > 0:
                            new_items_full += list(remaining_domains)[:available]
                        remaining_domains.difference_update(new_items_full)
                        if not new_items_full:
                            continue
                        lst = create_list(list_name, new_items_full)
                        self.cache["lists"].append(lst)
                        self.cache["mapping"][lst["id"]] = new_items_full
                        new_list_ids.append(lst["id"])
                        continue
                    info(
                        f"Updated list: {list_name} "
                        f"| Added {len(new_items)} domains,"
                        f"Removed {len(remove_items)} domains "
                        f"| Total domains in list: {len(chunk)}"
                    )
                    self.cache["mapping"][list_id] = list(chunk)
                else:
                    silent_error(
                        f"Skipped update list: {list_name} "
                        f"| Total domains in list: {len(chunk)}"
                    )
                
                new_list_ids.append(list_id)
            else:
                # Create new lists for remaining domains
                if remaining_domains:
                    needed_items = min(LIST_CAPACITY, len(remaining_domains))
                    new_items = list(remaining_domains)[:needed_items]
                    remaining_domains.difference_update(new_items)
                    lst = create_list(list_name, new_items)
                    info(f"Created list: {lst['name']} with {len(new_items)} domains")
                    self.cache["lists"].append(lst)
                    self.cache["mapping"][lst["id"]] = new_items
                    new_list_ids.append(lst["id"])

        # Update the rule with the new list IDs
        cgp_rule = next((rule for rule in current_rules if rule["name"] == self.rule_name), None)
        cgp_list_ids = utils.extract_list_ids(cgp_rule)
        block_traffic = self._list_traffic(new_list_ids)

        if cgp_rule:
            if set(new_list_ids) != cgp_list_ids:
                try:
                    updated_rule = update_rule(
                        self.rule_name, cgp_rule["id"], block_traffic, BLOCK_PRECEDENCE
                    )
                    info(f"Updated rule {updated_rule['name']}")
                    self.cache["rules"] = [updated_rule]
                except NotFoundException:
                    rule = create_rule(self.rule_name, block_traffic, BLOCK_PRECEDENCE)
                    info(f"Recreated rule {rule['name']}")
                    self.cache["rules"] = [rule]
            else:
                silent_error(f"Skipping rule update as list IDs are unchanged: {cgp_rule['name']}")
        else:
            rule = create_rule(self.rule_name, block_traffic, BLOCK_PRECEDENCE)
            info(f"Created rule {rule['name']}")
            self.cache["rules"].append(rule)

        # Allow rules take precedence over the block rule, so whitelisted
        # subdomains can be exempted even when their parent domain is blocked.
        self._sync_allow_rules(converter.whitelist_domains)

        # Now that the block rule no longer references the surplus lists,
        # they can be deleted safely.
        for lst in surplus_lists:
            try:
                delete_list(lst["id"])
                info(f"Deleted surplus list: {lst['name']}")
            except NotFoundException:
                info(f"Surplus list already gone: {lst['name']}")
            except HTTPException as exc:
                silent_error(f"Could not delete surplus list {lst['name']}: {exc}")

        utils.save_cache(self.cache)


    def delete_resources(self):
        current_lists = utils.get_current_lists(self.cache, self.list_name)
        # Query rules directly so block and allow rules are both removed.
        current_rules = get_rules(self.list_name)
        current_lists.sort(key=utils.safe_sort_key)

        # Delete rules whose names start with the list prefix
        for rule in current_rules:
            try:
                delete_rule(rule["id"])
                info(f"Deleted rule: {rule['name']}")
            except NotFoundException:
                info(f"Rule already gone: {rule['name']}")

            # Clear the rules cache after deletion
            self.cache["rules"] = []
            utils.save_cache(self.cache)

        # Delete lists with names that include prefix
        for lst in current_lists:
            try:
                delete_list(lst["id"])
                info(f"Deleted list: {lst['name']}")
            except NotFoundException:
                info(f"List already gone: {lst['name']}")

            # Remove the deleted list from the cache
            self.cache["lists"] = [item for item in self.cache["lists"] if item["id"] != lst["id"]]

            # Remove the mapping for the deleted list from the cache
            if lst["id"] in self.cache["mapping"]:
                del self.cache["mapping"][lst["id"]]

            # Save updated cache
            utils.save_cache(self.cache)


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Manager Script")
    parser.add_argument("action", choices=["run", "leave"], help="Choose action: run or leave")
    args = parser.parse_args()    
    cloudflare_manager = CloudflareManager(PREFIX)
    
    if args.action == "run":
        cloudflare_manager.update_resources()
        if utils.is_running_in_github_actions():
            utils.delete_cache()
    elif args.action == "leave":
        cloudflare_manager.delete_resources()
    else:
        error("Invalid action. Please choose either 'run' or 'leave'.")

if __name__ == "__main__":
    main()

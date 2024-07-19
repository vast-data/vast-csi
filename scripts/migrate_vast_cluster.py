"""
Script for migrating data between two VAST storages.

Usage:
    python migrate_vast_cluster.py --source-host <source_host> --destination-host <destination host> \
    --source-username <source_username> --source-password <source_password> --destination-username <destination username> --destination-password <destination password> --base-path=/k8s

Example:
    python migrate_vast_cluster.py --source-host 10.27.113.27 --destination-host 10.91.5.242 --source-username admin  --destination-username admin --source-password 123456 --destination-password 123456 --base-path=/k8s [--dry-run]
"""
import sys
import requests
import urllib3
import logging
import argparse

# Set up logging
logging.basicConfig(level=logging.INFO)
urllib3.disable_warnings()


class NoResourceFound(Exception):
    pass


class RestSession(requests.Session):

    def __init__(self, endpoint, username, password):
        super().__init__()
        self.verify = False
        self.auth = (username, password)
        self.base_url = f"https://{endpoint}/api/"
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)

        def func(*args, **params):
            res = self.request("get", f"{self.base_url}/{attr}", *args, timeout=10, params=params)
            res.raise_for_status()
            return res.json()

        func.__name__ = attr
        func.__qualname__ = f"{self.__class__.__qualname__}.{attr}"
        setattr(self, attr, func)
        return func

    def get_tenant(self, tenant_name):
        tenants = self.tenants(name=tenant_name)
        if tenants:
            return tenants[0]
        raise NoResourceFound(f"No such tenant {tenant_name}")

    def get_view_policy(self, policy_name: str):
        """Get view policy by name. Raise exception if not found."""
        viewpolicies = self.viewpolicies(name=policy_name)
        if viewpolicies:
            return viewpolicies[0]
        raise NoResourceFound(f"No such view policy {policy_name}")

    def get_view(self, path):
        views = self.views(path__contains=path)
        if views:
            return views[0]
        raise NoResourceFound(f"No such view path {path}")

    def get_views_by_pref(self, pref):
        return self.views(path__startswith=pref)

    def ensure_view(self, path, protocols, policy_id, tenant_id):
        try:
            self.get_view(path=path)
        except NoResourceFound:
            self.create_view(
                path=path, protocols=protocols, policy_id=policy_id, tenant_id=tenant_id
            )

    def create_view(self, path, protocols, policy_id, tenant_id, create_dir=True):
        data = {
            "path": path, "create_dir": create_dir,
            "protocols": protocols, "policy_id": policy_id, "tenant_id": tenant_id
        }
        res = self.post(f"{self.base_url}/views/", json=data)
        res.raise_for_status()

    def get_vip_pool(self, vip_pool_name):
        vip_pools = self.vippools(name=vip_pool_name)
        if vip_pools:
            return vip_pools[0]
        raise NoResourceFound(f"No such vip pool {vip_pool_name}")

    def get_quota(self, path):
        quotas = self.quotas(path__contains=path)
        if quotas:
            return quotas[0]
        raise NoResourceFound(f"No such quota path {path}")

    def ensure_quota(self, path, name, tenant_id, hard_limit):
        try:
            self.get_quota(path=path)
        except NoResourceFound:
            self.create_quota(path=path, name=name, tenant_id=tenant_id, hard_limit=hard_limit)

    def create_quota(self, path, name, tenant_id, hard_limit):
        data = {
            "path": path, "name": name,
            "tenant_id": tenant_id, "hard_limit": hard_limit
        }
        res = self.post(f"{self.base_url}/quotas/", json=data)
        res.raise_for_status()

    def get_qos_policy(self, policy_name):
        """Get QoS policy by name. Raise exception if not found."""
        qos_policies = self.qospolicies(name=policy_name)
        if qos_policies:
            return qos_policies[0]
        raise NoResourceFound(f"No such QOS policy {policy_name}")


def parse_arguments():
    parser = argparse.ArgumentParser(description="VCSI Migration - Recreate Quotas and Views for PVCs on a target Vast Cluster")
    parser.add_argument('--source-host', type=str, required=True, help='Source host IP or domain')
    parser.add_argument('--source-username', type=str, required=True, help='Source username')
    parser.add_argument('--source-password', type=str, required=True, help='Source password')
    parser.add_argument('--destination-host', type=str, required=True, help='Destination host IP or domain')
    parser.add_argument('--destination-username', type=str, required=True, help='Destination username')
    parser.add_argument('--destination-password', type=str, required=True, help='Destination password')
    parser.add_argument('--base-path', type=str, required=True, help='The root path for CSI related views (root_export)')
    parser.add_argument('--dry-run', action="store_true", help='Run in dry-run mode')
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_arguments()
    source_host = args.source_host
    source_username = args.source_username
    source_password = args.source_password
    destination_host = args.destination_host
    destination_username = args.destination_username
    destination_password = args.destination_password
    base_path = args.base_path
    dry_run = args.dry_run

    source_session = RestSession(endpoint=source_host, username=source_username, password=source_password)
    destination_session = RestSession(endpoint=destination_host, username=destination_username, password=destination_password)

    not_found = False
    vip_pools = source_session.vippools()
    for vip_pool in vip_pools:
        try:
            destination_session.get_vip_pool(vip_pool["name"])
        except NoResourceFound:
            not_found = True
            logging.warning(f"No such vip pool {vip_pool['name']}")

    if not_found:
        res = input("Missing vip pools detected. Do you want to proceed? [y/N]")
        if res.lower() not in ("y", "yes"):
            sys.exit(0)

    policies_mapping = {}
    tenants_mapping = {}

    views = source_session.get_views_by_pref(base_path)
    for view in views:
        tenant = view["tenant_name"]
        protocols = view["protocols"]
        policy = view["policy"]
        path = view["path"]
        try:
           quota = source_session.get_quota(path=path)
        except NoResourceFound:
            logging.warning(f"No such quota path {path}. Skipping sync for view.")
            continue

        tenant_id = tenants_mapping.get(tenant)
        if not tenant_id:
            tenant_id = destination_session.get_tenant(tenant)["id"]
            tenants_mapping[tenant] = tenant_id

        policy_id = policies_mapping.get(policy)
        if not policy_id:
            policy_id = destination_session.get_view_policy(policy)["id"]

        logging.info(f"Syncing view {path}")
        if dry_run:
            logging.info(f"Dry-run: (View: {path=}, {protocols=}, {policy_id=}, {tenant_id=})")
        else:
            destination_session.ensure_view(path=path, protocols=protocols, policy_id=policy_id, tenant_id=tenant_id)

        quota_name = quota["name"]
        hard_limit = quota["hard_limit"]

        logging.info(f"Syncing quota {quota_name}")
        if dry_run:
            logging.info(f"Dry-run: (Quota: {path=}, {quota_name=}, {tenant_id=}, {hard_limit=})")
        else:
            destination_session.ensure_quota(path=path, name=quota_name, tenant_id=tenant_id, hard_limit=hard_limit)

    logging.info("Completed!")
    logging.info(f"Total views: {len(views)}")

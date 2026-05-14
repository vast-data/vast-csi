terraform {
  required_providers {
    vastdata = {
      source  = "vast-data/vastdata"
      version = "~> 3.0"
    }
  }
}

# =============================
# Source Cluster (clusterA)
# =============================
provider "vastdata" {
  host            = "10.205.0.132"
  username        = "admin"
  password        = "123456"
  skip_ssl_verify = true
}
# Destination Cluster (clusterB)
provider "vastdata" {
  alias           = "clusterB"
  host            = "16.0.0.2"
  username        = "admin"
  password        = "123456"
  skip_ssl_verify = true
}
# Create replication VIP pool on source cluster
resource "vastdata_vip_pool" "replication_poolA" {
  name        = "gateway"
  role        = "REPLICATION"
  subnet_cidr = "24"
  ip_ranges = [
    ["20.0.0.1", "20.0.0.5"]
  ]
}
# Create replication VIP pool on destination cluster
resource "vastdata_vip_pool" "replication_poolB" {
  provider    = vastdata.clusterB
  name        = "gateway"
  role        = "REPLICATION"
  subnet_cidr = "24"
  ip_ranges = [
    ["20.0.0.6", "20.0.0.10"]
  ]
}
# Create replication peer on source cluster
resource "vastdata_replication_peer" "clusterA_clusterB_peer" {
  name        = "clusterA-clusterB-peer"
  leading_vip = vastdata_vip_pool.replication_poolB.start_ip
  pool_id     = vastdata_vip_pool.replication_poolA.id
}
# Protection policy A - 15 minute interval
resource "vastdata_protection_policy" "policyA" {
  name             = "policy-15m"
  clone_type       = "NATIVE_REPLICATION"
  indestructible   = false
  prefix           = "policy-15m"
  target_object_id = vastdata_replication_peer.clusterA_clusterB_peer.id
  frames = [{
    every       = "15M"
    keep_local  = "1H"
    keep_remote = "1H"
  }]
}

# Protection policy B - 1 hour interval
resource "vastdata_protection_policy" "policyB" {
  name             = "policy-1h"
  clone_type       = "NATIVE_REPLICATION"
  indestructible   = false
  prefix           = "policy-1h"
  target_object_id = vastdata_replication_peer.clusterA_clusterB_peer.id
  frames = [{
    every       = "1H"
    keep_local  = "4H"
    keep_remote = "4H"
  }]
}

# Protection policy C - 24 hour interval
resource "vastdata_protection_policy" "policyC" {
  name             = "policy-24h"
  clone_type       = "NATIVE_REPLICATION"
  indestructible   = false
  prefix           = "policy-24h"
  target_object_id = vastdata_replication_peer.clusterA_clusterB_peer.id
  frames = [{
    every       = "24H"
    keep_local  = "72H"
    keep_remote = "72H"
  }]
}

# =============================
# Optionally create additional subsystems
# =============================
#
resource "vastdata_view" "clusterA_subsystem" {
    name = "source"
    path = "/source"
    policy_id = 1
    protocols = ["BLOCK"]
}

resource "vastdata_view" "clusterB_subsystem" {
    provider = vastdata.clusterB
    name = "destination"
    path = "/destination"
    policy_id = 1
    protocols = ["BLOCK"]
}

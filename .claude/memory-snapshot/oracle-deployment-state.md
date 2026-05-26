---
name: oracle-deployment-state
description: "Operator's Oracle Cloud + oci-cli state — PAYG unlocked but Frankfurt still out of capacity"
metadata: 
  node_type: memory
  type: project
  originSessionId: f74bda56-2f2e-4c8c-88a2-3b5fabb2aab4
---

**As of 2026-05-25 ~14:18 CEST:** PAYG upgrade completed (A1 limits unlocked from 4→16/41 cores regional/AD), but Frankfurt is still hardware-out-of-capacity in all 3 ADs and Stockholm subscription is blocked by `TenantCapacityExceeded` — the region-subscription cap stayed at 1. Retry loop v3 still hunting in background.

## Tenancy

- **Tenant:** `ahmedhobeishytools`
- **Tenancy OCID:** `ocid1.tenancy.oc1..aaaaaaaap4xmyscyghnxxfowtfg44vo3an7h6yktvcrexnw6tdcyfvc2wn6a`
- **User OCID:** `ocid1.user.oc1..aaaaaaaadysdvmfm743anwn42hriqkyv6allnzi4t3ylr2a5hb7z2z4aez4a`
- **Home region:** `eu-frankfurt-1` (permanent; cannot subscribe additional regions until tenant capacity is increased)
- **Account type:** PAYG (upgraded ~2026-05-25 mid-day; A1 limits jumped from free-tier 4 cores/24GB to 16 cores/96GB regional, 41/277 per AD)

## A1.Flex capacity (as of 14:18 CEST)

- **Limits:** unlocked (PAYG defaults)
  - `standard-a1-core-regional-count`: 16
  - `standard-a1-memory-regional-count`: 96
  - per-AD: 41 cores / 277 GB
- **Actual capacity:** still **out of capacity** in all 3 Frankfurt ADs — every retry attempt returns `out of host capacity`. Limits unlocking doesn't conjure hardware; Frankfurt is genuinely saturated.

## Region subscription block

Tried `oci iam region-subscription create --region-key ARN` → returns `TenantCapacityExceeded: You have exceeded the maximum number of allowed subscribed regions`. PAYG normally allows multiple regions but this tenant's region-subscription cap is still 1. Possible causes: (a) PAYG fraud-prevention hold for first 30 days; (b) cap needs to be requested via Oracle Console "Limits, Quotas and Usage" page. The operator would need to navigate that flow themselves.

## Local oci-cli config

- Config: `~/.oci/config`
- API key fingerprint (Oracle-side): `c8:ec:40:6d:9b:06:29:d1:c3:89:e1:52:d3:3d:f8:d1`
- Private key: `~/.oci/oci_api_key.pem`
- ⚠️ My local openssl fingerprint computation gave `e7:9d:b0:...` but Oracle stored `c8:ec:40:...` — trust the Oracle Console fingerprint, not local openssl piping.

## Network resources (created via oci-cli — Frankfurt)

- **VCN:** `ocid1.vcn.oc1.eu-frankfurt-1.amaaaaaa7tpoyniac7yhh3sgy2dr4foqwff4wfpjvbcndrpsy4dv73meslda` (`lumen-vcn`, CIDR `10.0.0.0/16`)
- **Internet Gateway:** `ocid1.internetgateway.oc1.eu-frankfurt-1.aaaaaaaaznt4xmegopkvk3m5o2rcq42f3v6zuagkwwn247ugiwrbie5tmeua`
- **Default route table:** `ocid1.routetable.oc1.eu-frankfurt-1.aaaaaaaadnw7rjeyokfp7nowqudjuts4hf5mpzl5yidnqgivsq3ccp6fqtdq` (rule `0.0.0.0/0 → IGW`)
- **Default security list:** `ocid1.securitylist.oc1.eu-frankfurt-1.aaaaaaaaabrxai6m35c574lzfuz3pujk2xvbjgdmij7hqdfykk233e6v4p4a` (ingress 22, 80, 443)
- **Public subnet:** `ocid1.subnet.oc1.eu-frankfurt-1.aaaaaaaacoxh73w336bcld3qamkmjo7vvamygt4f7zvnnz5ynhwueey4mi3a` (`lumen-public-subnet`, CIDR `10.0.0.0/24`)
- **Image** (`Canonical-Ubuntu-24.04-Minimal-aarch64-2026.04.30-1`): `ocid1.image.oc1.eu-frankfurt-1.aaaaaaaa33mxho6qsnmm4yu7xo3nrnvjubiimgqpsc5ycpoakz6pb4cts2ma`
- **SSH key for VM:** `~/.ssh/id_ed25519` (private), `~/.ssh/id_ed25519.pub` (public, also passed to instance launch)

## Background retry loop

- Script: `~/.oci/retry_loop.ps1` (v3: polite 60s cadence + 429 backoff)
- Log: `~/.oci/retry.log`
- PID file: `~/.oci/retry.pid` (current PID 14896)
- Shape config: `~/.oci/shape_cfg.json` (`{"ocpus":4,"memoryInGBs":24}`)
- Status helper: `pwsh -NoProfile -File ~/.oci/status.ps1`
- Cycles AD-1 → AD-2 → AD-3, 60s between attempts, breaks on `lifecycle-state: PROVISIONING|RUNNING`.

## What's complete and what's blocked

| Step | State |
|---|---|
| Oracle signup | ✅ done (Frankfurt home region locked) |
| oci-cli installed + configured | ✅ done |
| API key uploaded | ✅ done (fingerprint `c8:ec:40:...`) |
| VCN + subnet + IGW + route + sec list | ✅ done |
| SSH key generated for VM | ✅ done |
| PAYG upgrade | ✅ done (A1 limits now PAYG defaults) |
| Retry loop launched | ✅ running v3 (background, polite cadence) |
| Stockholm region subscription | ⏳ blocked on tenant region-subscription cap (`TenantCapacityExceeded`) |
| VM landed | ⏳ blocked on Frankfurt A1 hardware capacity |
| Step 3 deploy + Step 4 eval + Step 7 push | ⏳ blocked on VM landing |
| **Step 5 MCP publish** | ✅ **done** — `io.github.ahmedEid1/lumen` v1.1.0 live at `https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen` |
| **Step 6 Loom** | ✅ **silent captioned walkthrough autonomously recorded** — `docs/screencast/walkthrough.mp4` committed; voiced Loom deferred until a live URL exists |

## What the operator needs to do (when ready)

1. Navigate to Oracle Console → Limits, Quotas and Usage → request a region-subscription cap increase. (Free-tier-to-PAYG bridge state has the regional sub cap still at 1.)
2. Once Stockholm subscribes, the retry loop pivots there automatically *if* updated — currently it's hardcoded to Frankfurt ADs, so a `retry_loop.ps1` v4 would need to probe both regions.
3. Alternative — wait for Frankfurt A1 capacity to free up organically. Could be hours, days, weeks. The retry loop will catch it.

## To resume / check status

```powershell
# Status
pwsh -NoProfile -File "$env:USERPROFILE\.oci\status.ps1"

# Restart loop if killed
$proc = Start-Process powershell -ArgumentList "-NoProfile","-File","$env:USERPROFILE\.oci\retry_loop.ps1" -WindowStyle Hidden -PassThru
$proc.Id | Set-Content "$env:USERPROFILE\.oci\retry.pid"

# Once it lands a VM, get the public IP
$tenancy='ocid1.tenancy.oc1..aaaaaaaap4xmyscyghnxxfowtfg44vo3an7h6yktvcrexnw6tdcyfvc2wn6a'
$vmId = oci compute instance list --compartment-id $tenancy --query 'data[?contains(\"display-name\", `lumen`)] | [0].id' --raw-output
oci compute instance list-vnics --instance-id $vmId --query 'data[0].\"public-ip\"' --raw-output
```

## How to apply when re-entering

- Read `docs/release/operator-activation-runbook.md` for the original plan
- Read this memory for what state the Oracle side is actually in
- Check the retry log first. If a VM landed, the rest of the deploy chain becomes straightforward
- If the retry loop has been killed, restart it with the snippet above
- The walkthrough screencast no longer depends on Oracle — `docs/screencast/walkthrough.mp4` ships as-is

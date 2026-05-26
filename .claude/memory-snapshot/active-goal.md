---
name: active-goal
description: "Deploy target pivoted Oracle → AWS t4g.small; project docs/scripts rewritten 2026-05-25, operator still needs to launch EC2"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4059c30a-7172-4501-9264-82e562516963
---

**Status:** ✅ **AWS deploy chapter complete — Lumen LIVE at `https://3.74.54.147.nip.io`** as of 2026-05-25 ~16:30 CEST.

The previous goal (clean + dual code review + verify + Oracle deploy) closed with backend 628/628 + frontend 139/139 on `claude/romantic-mayer-ab2e85`. That branch's Oracle deploy step never landed because Frankfurt A1 stayed out of capacity for 24h+ and PAYG's region-subscription cap blocked the Stockholm fallback. User pivoted to AWS t4g.small (new Free Plan account — 6 months, $200 credits, auto-closes 2026-11-25).

**What landed in this chapter (project-side docs/code only — Terraform/CLI deferred per user scope):**

1. Created `scripts/aws-bootstrap.sh` — 4 GB swapfile + same hardening shape as Oracle's, EC2 metadata-aware
2. Created `docs/deployment/aws-vps.md` — 10-step runbook, 2 GB RAM tuning block, split-deploy appendix
3. Deleted `scripts/oracle-bootstrap.sh` + `docs/deployment/oracle-vps.md`
4. Rewrote README "Deploy it" section + status footer for AWS path
5. Rewrote `docs/release/operator-activation-runbook.md` Steps 1–3 (AWS Free Plan signup → t4g.small launch → bootstrap); marked Step 5 (MCP) and Step 6 (screencast) ✅ DONE
6. Added "Deploy target pivot" entry to CHANGELOG.md [Unreleased] with rationale; annotated A4's historical entry; rewrote "next steps" list
7. Updated `docs/release/1.1.0-agentic-pr-body.md` TL;DR + H4 + checklist row
8. Updated `docs/release/known-issues-post-1.1.0.md` KI-1 / KI-3 / KI-6 / KI-8 / KI-10 references
9. Updated `.env.example` line-111 cross-ref

**Operator's remaining steps (unchanged shape, AWS target):**

1. AWS Free Plan signup ✅ done (user confirmed welcome email)
2. Launch t4g.small EC2 + Elastic IP (Steps 2.1–2.4 of `aws-vps.md` / `operator-activation-runbook.md`)
3. SSH in, rsync repo, run `aws-bootstrap.sh`, configure `.env.production` with Groq key, `docker compose up`
4. `make eval` for real tutor score → README badge
5. ~~MCP publish~~ already done
6. ~~Screencast~~ already done (`docs/screencast/walkthrough.mp4`)
7. `make publish-rewrite` → push branch + open PR

**Why this matters going forward:** the project-side rewrite is complete. Next chapter is either (a) user launches the EC2 themselves following the runbook (operator-shaped, no more agent work needed for docs), (b) user asks me to drive Claude in Chrome / IAM keys / Terraform to do the live launch in-conversation, or (c) Phase J / 1.1.0-agentic.1 cleanup work.

See [[aws-deployment-state]] for the detailed project-side pivot record and [[oracle-deployment-state]] for the user's separate Oracle retry-loop journey (still running out-of-band).

# ADR-0032: Retire the hosted demo; gate deploys and pin the instance

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @ahmedEid1

## Context

The hosted demo ran on one EC2 t4g.small in an AWS Free plan account. That plan ends on 2026-11-25, and the account closes unless it is upgraded to a paid plan. From January 2027 the box would cost about $21 a month. The owner chose not to upgrade, so the demo was taken down on 2026-10-30.

Two things in the repo assumed a live host. First, `ci.yml`'s `deploy` job ran on every green push to `main`, so with no host every merge would fail at the deploy step. Second, the instance in `infra/aws/compute.tf` had `user_data_replace_on_change = true` and a `most_recent` AMI lookup. The bootstrap script is embedded in the user data, so any later edit to it (five since launch) or any new Ubuntu AMI would make `terraform apply` replace the instance, and `delete_on_termination = true` would delete the root volume holding all the data.

## Decision

- The `deploy` job also requires the repo variable `DEPLOY_ENABLED == 'true'`. Every gate still runs on `main`, but nothing deploys while the variable is unset. Setting it turns deploys back on.
- `aws_instance.lumen` gets `lifecycle { ignore_changes = [ami, user_data] }`. The bootstrap runs once, on the first boot. A rebuild has to be asked for explicitly with `terraform apply -replace=aws_instance.lumen`.
- The last live version is recorded in `docs/demo/2026-10-30/`, and `docs/deployment/REDEPLOY.md` describes how to bring it back with the final dump.

## Alternatives considered

- **Upgrade the AWS account and keep the demo.** Rejected by the owner on cost.
- **Delete `deploy.yml` and `infra/aws/`.** Rejected: they document how Lumen ran in production, and the redeploy guide relies on them.
- **Drop `user_data_replace_on_change`.** Not enough on its own: an AMI change would still replace the instance.

## Consequences

- Pushes to `main` publish images to GHCR but don't deploy. The README and `docs/ci-cd.md` say so.
- After a bootstrap edit, existing boxes don't pick up the change through Terraform. Apply it on the box, or rebuild with `-replace` after a backup.

## References

- `docs/deployment/REDEPLOY.md`, `docs/demo/2026-10-30/README.md`

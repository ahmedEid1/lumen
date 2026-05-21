# Incident response runbook

## Severity levels

| Sev  | Definition | Examples | Response |
|------|-----------|----------|----------|
| SEV1 | Complete outage / data loss risk | API 5xx > 50% sustained; Postgres down | All-hands; status page within 5 min; postmortem within 5 business days |
| SEV2 | Major degraded function | Chat down; uploads failing | On-call paged; status page within 15 min; postmortem within 10 business days |
| SEV3 | Minor degraded function | Search returning stale results; slow endpoint | Ticket; fix within sprint |
| SEV4 | Cosmetic / single-user | UI glitch | Ticket; fix when convenient |

## First-response checklist

1. **Acknowledge** the page in the incident channel.
2. **Declare** severity and open a thread.
3. **Mitigate** before diagnosing — roll back, scale up, failover.
4. **Communicate** status to users (status page / banner) every 30 min.
5. **Diagnose** root cause once stable.
6. **Resolve** and close the incident.
7. **Postmortem** within the SLA above (blameless template in `docs/postmortems/_template.md`).

## Common diagnostics

```bash
# Service health
curl -fsS https://$APP_DOMAIN/api/v1/health/ready | jq

# DB inflight
docker compose -f docker-compose.prod.yml exec db \
  psql -U lumen -d lumen -c "select state, count(*) from pg_stat_activity group by state;"

# Redis pressure
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli info memory | head

# Slow queries (last hour)
docker compose -f docker-compose.prod.yml exec db \
  psql -U lumen -d lumen -c "select query, calls, mean_exec_time \
   from pg_stat_statements order by mean_exec_time desc limit 20;"

# Worker queue depth
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli llen celery
```

## Roll back

```bash
cd /opt/lumen
git checkout v<previous-tag>
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

## Escalation

- Primary: on-call rotation (PagerDuty `lumen-prod`).
- Secondary: maintainer of the affected component (CODEOWNERS).
- Final: project lead (@ahmedEid1).

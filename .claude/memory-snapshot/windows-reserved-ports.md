---
name: windows-reserved-ports
description: "This Windows / WSL2 machine reserves TCP 7681-7780 and similar ranges; docker host port bindings in those ranges fail with \"ports are not available\""
metadata: 
  node_type: memory
  type: project
  originSessionId: 570ed99c-48b3-471c-a2d9-c72712d55445
---

This user's Windows / WSL2 host reserves these TCP port ranges
(check with `netsh interface ipv4 show excludedportrange protocol=tcp`):

- 1028-1527 (Hyper-V dynamic)
- 7681-7780  ← **Meilisearch default 7700 lives here**
- 7781-7880
- 8224-8523
- 8624-8823

When iter 98 first brought the stack up, `docker compose up` failed
with `ports are not available: exposing port TCP 0.0.0.0:7700 ->
127.0.0.1:0`. The fix in `docker-compose.yml` was to remove the host
binding entirely for the `search` service — the API reaches
meilisearch via the docker network at `http://search:7700`, so the
host binding only matters for direct curl / web-UI debugging.

**Apply to future iterations**: if you add a new service that wants
to bind a host port in any of those ranges, either pick a port
outside the reserved ranges or drop the host binding and use the
docker network. Don't try to "fix" the reservation — it's set by
Hyper-V on every boot.

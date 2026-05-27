-- RESERVE_COST (L21-Sec)
--
-- Atomic per-user + per-IP + per-global 24h spend reservation in
-- microcents (1 USD = 1_000_000 microcents). Integer arithmetic so
-- there's zero FP drift across re-runs (plan-v7 §V7-F5).
--
-- KEYS:
--   1. user_key   (e.g. cost:user:u_abc:2026-05-27)
--   2. ip_key     (e.g. cost:ip:1.2.3.4:2026-05-27)
--   3. global_key (e.g. cost:global:2026-05-27)
--
-- ARGV:
--   1. estimate_microcents (positive integer; refused if <= 0)
--   2. max_user_24h_microcents
--   3. max_ip_24h_microcents
--   4. max_global_24h_microcents
--   5. ttl_seconds (typically 86400; only applied to keys created here)
--
-- Returns: {1, "ok"} on success, {0, "<cap_name>"} on cap exceeded,
--          {0, "invalid_estimate"} on bad ARGV[1].
--
-- Cap-name values:
--   "user_cap" / "ip_cap" / "global_cap" / "invalid_estimate"

local estimate = tonumber(ARGV[1])
if estimate == nil or estimate <= 0 then
  return {0, "invalid_estimate"}
end
local max_user = tonumber(ARGV[2])
local max_ip = tonumber(ARGV[3])
local max_global = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

-- Pre-flight read of all three buckets. Pure GET, no side effects.
-- Negative-balance floor at zero so a buggy prior RECONCILE can't
-- make the new estimate seem cheap.
local user_spent = math.max(0, tonumber(redis.call("GET", KEYS[1]) or "0"))
local ip_spent = math.max(0, tonumber(redis.call("GET", KEYS[2]) or "0"))
local global_spent = math.max(0, tonumber(redis.call("GET", KEYS[3]) or "0"))

if user_spent + estimate > max_user then return {0, "user_cap"} end
if ip_spent + estimate > max_ip then return {0, "ip_cap"} end
if global_spent + estimate > max_global then return {0, "global_cap"} end

-- Commit. EXPIRE only on key creation (plan-v7 §V6-F6 sliding-TTL
-- fix); subsequent INCRBYs preserve the existing TTL so the 24h
-- window doesn't reset every spend.
local function bump(key)
  local was_new = (redis.call("EXISTS", key) == 0)
  redis.call("INCRBY", key, estimate)
  if was_new and ttl > 0 then
    redis.call("EXPIRE", key, ttl)
  end
end

bump(KEYS[1])
bump(KEYS[2])
bump(KEYS[3])

return {1, "ok"}

-- CHECK_CONCURRENCY (L21-Sec)
--
-- Atomic INCR + TTL on a per-user concurrent-streams counter. Returns
-- {1, current} on acquire, {0, current} on cap exceeded.
--
-- Key shape: concurrent:user:{user_id}
--
-- KEYS:
--   1. user_key  (concurrent:user:<user_id>)
--
-- ARGV:
--   1. max_concurrent (integer, typically 3)
--   2. ttl_seconds    (counter lifetime — protects against stuck rows;
--                      callers should also call RELEASE_CONCURRENCY)
--
-- Returns: {1, current_count} on acquire, {0, current_count} on cap.

local max = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = tonumber(redis.call("GET", KEYS[1]) or "0")

if current >= max then
  return {0, current}
end

-- Acquire. INCR then EXPIRE-on-first only. Subsequent increments
-- preserve the existing TTL.
local was_new = (redis.call("EXISTS", KEYS[1]) == 0)
local new_val = redis.call("INCR", KEYS[1])
if was_new and ttl > 0 then
  redis.call("EXPIRE", KEYS[1], ttl)
end

return {1, new_val}

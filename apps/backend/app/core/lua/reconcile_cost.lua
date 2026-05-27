-- RECONCILE_COST (L21-Sec)
--
-- Adjust a previous reservation by ``delta`` (positive = spent more
-- than reserved; negative = release the over-reservation).
--
-- Bounded at zero and with a tagged-error result for absurd deltas
-- (plan-v7 §V7-F5). When the adjusted value lands at zero AND the key
-- existed before the call, the key is DEL'd to avoid permanent zero
-- balances; if the key didn't exist and delta is negative, the call
-- is a no-op (no key to adjust).
--
-- KEYS:
--   1. user_key
--   2. ip_key
--   3. global_key
--
-- ARGV:
--   1. delta_microcents (signed integer)
--   2. max_delta_magnitude_microcents (abs cap; refuses on absurd values)
--
-- Returns: {1, "ok"} or {0, "delta_too_large"}.

local delta = tonumber(ARGV[1])
local max_magnitude = tonumber(ARGV[2])

if math.abs(delta) > max_magnitude then
  return {0, "delta_too_large"}
end

local function adjust(key)
  local exists_before = (redis.call("EXISTS", key) == 1)
  if not exists_before and delta <= 0 then
    -- Nothing to release on a non-existent key.
    return
  end
  local current = math.max(0, tonumber(redis.call("GET", key) or "0"))
  local ttl = redis.call("TTL", key)
  local new_val = math.max(0, current + delta)

  if new_val == 0 and exists_before then
    -- Don't leave a permanent zero key. The next RESERVE will
    -- recreate it with a fresh 24h TTL.
    redis.call("DEL", key)
  elseif new_val == 0 and not exists_before then
    -- Was never created and delta is positive but the new value
    -- still rounds to zero — nothing to do.
    return
  else
    redis.call("SET", key, tostring(new_val))
    if ttl > 0 then
      -- Preserve the remaining 24h window (don't slide).
      redis.call("EXPIRE", key, ttl)
    else
      -- Key existed but had no TTL (unusual — RESERVE always sets
      -- one). Set a fresh window so it doesn't live forever.
      redis.call("EXPIRE", key, 86400)
    end
  end
end

adjust(KEYS[1])
adjust(KEYS[2])
adjust(KEYS[3])

return {1, "ok"}

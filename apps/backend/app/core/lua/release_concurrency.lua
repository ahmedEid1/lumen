-- RELEASE_CONCURRENCY (L21-Sec)
--
-- Decrement the per-user concurrent-streams counter. Floors at zero,
-- DELs the key when the count drops to zero so it doesn't sit at 0
-- with a TTL ticking down (which would behave correctly but waste a
-- Redis key).
--
-- Used by the Celery task's finally block to ensure a turn that
-- exits — successfully or not — releases its slot back to the user.
-- plan-v7 §V7-F1 made this user-scoped (was wrongly drafted as
-- turn-scoped in v5).
--
-- KEYS:
--   1. user_key
--
-- Returns: {new_value}.

local current = tonumber(redis.call("GET", KEYS[1]) or "0")
if current <= 0 then
  -- Already at zero (or never existed). No-op.
  if redis.call("EXISTS", KEYS[1]) == 1 then
    redis.call("DEL", KEYS[1])
  end
  return {0}
end

local new_val = redis.call("DECR", KEYS[1])
if new_val <= 0 then
  redis.call("DEL", KEYS[1])
  return {0}
end
return {new_val}

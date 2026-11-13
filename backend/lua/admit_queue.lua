local p = KEYS[1]
local t = redis.call('TIME')
local now = tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local waiting,admitted,entries = p..'q:waiting',p..'q:admitted',p..'q:entry'
local updates = {}
local expired = redis.call('ZRANGEBYSCORE',admitted,'-inf',now)
for _,sid in ipairs(expired) do
    local entry = cjson.decode(redis.call('HGET',entries,sid))
    entry.status = 'EXPIRED'
    redis.call('HSET',entries,sid,cjson.encode(entry))
    redis.call('ZREM',admitted,sid)
    table.insert(updates,{sid=sid,status='EXPIRED'})
end
if ARGV[3] ~= '' then
    local sid = ARGV[3]
    local raw = redis.call('HGET',entries,sid)
    if raw then
        local entry = cjson.decode(raw)
        entry.status = 'COMPLETED'
        redis.call('HSET',entries,sid,cjson.encode(entry))
        redis.call('ZREM',admitted,sid)
        table.insert(updates,{sid=sid,status='COMPLETED'})
    end
end
local free = tonumber(ARGV[1])-redis.call('ZCARD',admitted)
if free > 0 then
    local next_up = redis.call('ZRANGE',waiting,0,free-1)
    for _,sid in ipairs(next_up) do
        local entry = cjson.decode(redis.call('HGET',entries,sid))
        entry.status = 'ADMITTED'
        entry.until_ms = now+tonumber(ARGV[2])
        redis.call('HSET',entries,sid,cjson.encode(entry))
        redis.call('ZREM',waiting,sid)
        redis.call('ZADD',admitted,entry.until_ms,sid)
        redis.call('ZADD',p..'q:recent',now,sid)
        table.insert(updates,{sid=sid,status='ADMITTED',until_ms=entry.until_ms,at=now})
    end
end
redis.call('ZREMRANGEBYSCORE',p..'q:recent','-inf',now-60000)
if #updates > 0 then redis.call('PUBLISH',p..'queue-events','changed') end
return cjson.encode(updates)

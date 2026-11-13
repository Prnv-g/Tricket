local p,id,sid,operation = KEYS[1],ARGV[1],ARGV[2],ARGV[3]
local raw = redis.call('HGET',p..'holds',id)
if not raw then return 'MISSING' end
local hold = cjson.decode(raw)
if hold.session_id ~= sid then return 'MISSING' end
local t = redis.call('TIME')
local now = tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
if operation == 'begin' then
    if hold.expires_at<=now then return 'EXPIRED' end
    if hold.status ~= 'ACTIVE' then return 'BUSY' end
    hold.status = 'COMMITTING'
    redis.call('HSET',p..'holds',id,cjson.encode(hold))
    redis.call('ZADD',p..'deadlines',now+10000,id)
    return 'OK'
end
if operation == 'retry' and hold.expires_at>now then
    hold.status = 'ACTIVE'
    redis.call('HSET',p..'holds',id,cjson.encode(hold))
    redis.call('ZADD',p..'deadlines',hold.expires_at,id)
    return 'OK'
end
if operation == 'expire' and hold.expires_at>now then return 'ACTIVE' end
local sold = operation == 'sold'
local changes = {}
for _,seat in ipairs(hold.seats) do
    if redis.call('HGET',p..'seats',seat)==id then
        if sold then redis.call('HSET',p..'seats',seat,'SOLD')
        else redis.call('HDEL',p..'seats',seat) end
        table.insert(changes,seat)
    end
end
redis.call('HDEL',p..'holds',id)
if redis.call('HGET',p..'active',sid)==id then redis.call('HDEL',p..'active',sid) end
redis.call('ZREM',p..'deadlines',id)
if #changes>0 then
    local version = redis.call('INCR',p..'version')
    redis.call('PUBLISH',p..'seat-events',cjson.encode({
        version=version,generation=redis.call('GET',p..'generation'),seats=changes,
        status=sold and 'SOLD' or 'AVAILABLE'
    }))
end
if operation=='expire' or operation=='retry' then
    redis.call('HINCRBY',p..'abandoned',sid,1)
    redis.call('HINCRBY','metrics:counts','expired_holds',1)
end
return 'OK'

local p,sid,id = KEYS[1],ARGV[1],ARGV[2]
local seats,duration = cjson.decode(ARGV[3]),tonumber(ARGV[4])
local t = redis.call('TIME')
local now = tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
if not redis.call('GET',p..'ready') then return {'NOT_READY'} end
local admitted_until = tonumber(redis.call('ZSCORE',p..'q:admitted',sid) or '0')
if admitted_until <= now then return {'NOT_ADMITTED'} end
if redis.call('HEXISTS',p..'active',sid)==1 then return {'ALREADY_HOLDING'} end
for _,seat in ipairs(seats) do
    if redis.call('HEXISTS',p..'seats',seat)==1 then return {'SEAT_TAKEN'} end
end
local hold = {id=id,session_id=sid,seats=seats,expires_at=now+duration,status='ACTIVE'}
redis.call('HSET',p..'holds',id,cjson.encode(hold))
redis.call('HSET',p..'active',sid,id)
redis.call('ZADD',p..'deadlines',hold.expires_at,id)
for _,seat in ipairs(seats) do redis.call('HSET',p..'seats',seat,id) end
local version = redis.call('INCR',p..'version')
redis.call('PUBLISH',p..'seat-events',cjson.encode({
    version=version,generation=redis.call('GET',p..'generation'),seats=seats,status='HELD'
}))
return {'OK',cjson.encode(hold)}

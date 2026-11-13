local p,sid = KEYS[1],ARGV[1]
local raw = redis.call('HGET',p..'q:entry',sid)
if not raw then return false end
local entry = cjson.decode(raw)
if entry.status == 'WAITING' then
    local rank = redis.call('ZRANK',p..'q:waiting',sid)
    if rank then entry.position=rank+1 end
    local rate = redis.call('ZCARD',p..'q:recent')
    if rank and rate>0 then entry.eta_seconds=math.ceil((rank+1)*60/rate) end
end
return cjson.encode(entry)

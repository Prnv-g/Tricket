local p = KEYS[1]
local generation = redis.call('GET',p..'generation')
if not generation or not redis.call('GET',p..'ready') then
    if ARGV[1]=='full' then redis.call('HINCRBY','metrics:counts','cache_misses',1) end
    return {}
end
local result = {generation,redis.call('GET',p..'version') or '0'}
if ARGV[1]=='full' then
    redis.call('HINCRBY','metrics:counts','cache_hits',1)
    table.insert(result,redis.call('HGETALL',p..'seats'))
end
return result

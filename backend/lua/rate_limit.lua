-- Check all limits before incrementing either bucket.
for i,key in ipairs(KEYS) do
    local count = tonumber(redis.call('GET',key) or '0')
    if count >= tonumber(ARGV[i]) then
        return math.max(1,redis.call('TTL',key))
    end
end
for _,key in ipairs(KEYS) do
    if redis.call('INCR',key) == 1 then redis.call('EXPIRE',key,tonumber(ARGV[#KEYS+1])) end
end
return 0

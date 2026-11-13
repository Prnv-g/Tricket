local p,sid,qid = KEYS[1],ARGV[1],ARGV[2]
local existing = redis.call('HGET',p..'q:entry',sid)
if existing then return existing end
local sequence = redis.call('INCR',p..'q:sequence')
local entry = cjson.encode({id=qid,sequence=sequence,status='WAITING'})
redis.call('HSET',p..'q:entry',sid,entry)
redis.call('ZADD',p..'q:waiting',sequence,sid)
return entry

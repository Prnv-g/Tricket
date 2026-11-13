# Architecture decision record

## Shared temporary state and durable ticket issuance

**Status** · Accepted for the hackathon demo.

**Redis Lua** makes group holds and FIFO admission atomic across replicas. The Redis clock supplies deadlines and an indexed expiry scan releases overdue holds. A version counter and Redis Pub/Sub deliver inexpensive updates to both processes.

**PostgreSQL** is the final authority for issued tickets. The unique event-seat constraint prevents a second ticket for the same seat. Reservation and payment uniqueness constrain successful bookings and replayed charges. The simulated provider records the charge and issues tickets in one transaction. A per-event advisory lock and a dirty projection marker coordinate PostgreSQL commits with Redis updates and recovery. This bounds correctness complexity at the cost of serializing mutations for one event.

**Two stateless FastAPI replicas** exercise balancing, restart recovery, and WebSocket reconnection without sticky sessions. Both share PostgreSQL, Redis, configuration, and the model artifact. WebSocket connections exist in the replica that accepted them.

**Dependency failure** blocks booking writes while Redis or PostgreSQL cannot be reached. On Redis restart, the APIs rebuild inventory and the queue from committed PostgreSQL rows before allocating seats. A transaction interrupted before commit leaves no successful simulated charge. Read-only booking lookups still use PostgreSQL. Redis AOF improves durability and the SQL projection remains the recovery authority.

**Pub/Sub reconciliation** is necessary because a subscriber can miss messages while disconnected. Generation and version checks let the client recover with a fresh snapshot.

**Production tradeoffs** include replacing the per-event mutation lock with narrower locking plus a durable outbox, adding high availability to the data services, and implementing gateway authorization, capture, and webhook reconciliation. Anonymous sessions and synthetic classifier evaluation limit fraud assurance. The checkout simulator proves transaction and replay behavior with a local logical charge.

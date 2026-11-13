CREATE TABLE IF NOT EXISTS users (
    id text PRIMARY KEY, session_id text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS events (
    id text PRIMARY KEY, title text NOT NULL, venue text NOT NULL,
    starts_at timestamptz NOT NULL, capacity integer NOT NULL CHECK (capacity > 0),
    demo boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS seats (
    id integer NOT NULL, event_id text NOT NULL REFERENCES events ON DELETE CASCADE,
    section integer NOT NULL, row_number integer NOT NULL, seat_number integer NOT NULL,
    price integer NOT NULL CHECK (price > 0), tier text NOT NULL,
    PRIMARY KEY (event_id, id), UNIQUE (event_id, section, row_number, seat_number)
);
CREATE TABLE IF NOT EXISTS queue_entries (
    id text PRIMARY KEY, event_id text NOT NULL REFERENCES events ON DELETE CASCADE,
    session_id text NOT NULL REFERENCES users(session_id), sequence bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('WAITING', 'ADMITTED', 'EXPIRED', 'COMPLETED')),
    joined_at timestamptz NOT NULL DEFAULT now(), admitted_at timestamptz, admitted_until bigint,
    UNIQUE(event_id, session_id), UNIQUE(event_id, sequence)
);
CREATE INDEX IF NOT EXISTS queue_active ON queue_entries(event_id, status, sequence);
CREATE TABLE IF NOT EXISTS reservations (
    id text PRIMARY KEY, event_id text NOT NULL REFERENCES events ON DELETE CASCADE,
    session_id text NOT NULL REFERENCES users(session_id),
    status text NOT NULL CHECK (status IN ('ACTIVE', 'COMMITTING', 'CONFIRMED', 'EXPIRED', 'CANCELLED')),
    expires_at bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    idempotency_key text NOT NULL, UNIQUE(event_id, session_id, idempotency_key),
    UNIQUE(id, event_id), UNIQUE(id, session_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS reservations_one_active
    ON reservations(event_id, session_id) WHERE status IN ('ACTIVE', 'COMMITTING');
CREATE INDEX IF NOT EXISTS reservations_expiry ON reservations(event_id, expires_at)
    WHERE status IN ('ACTIVE', 'COMMITTING');
CREATE TABLE IF NOT EXISTS reservation_seats (
    reservation_id text NOT NULL, event_id text NOT NULL, seat_id integer NOT NULL,
    PRIMARY KEY(reservation_id, seat_id),
    FOREIGN KEY(reservation_id, event_id) REFERENCES reservations(id, event_id) ON DELETE CASCADE,
    FOREIGN KEY(event_id, seat_id) REFERENCES seats(event_id, id)
);
CREATE INDEX IF NOT EXISTS reservation_seats_lookup ON reservation_seats(event_id, seat_id);
CREATE TABLE IF NOT EXISTS payments (
    id text PRIMARY KEY, reservation_id text NOT NULL REFERENCES reservations ON DELETE CASCADE,
    idempotency_key text NOT NULL UNIQUE, provider_reference text UNIQUE,
    mode text NOT NULL CHECK(mode IN ('success', 'decline', 'timeout')),
    status text NOT NULL CHECK(status IN ('PROCESSING', 'SUCCEEDED', 'FAILED')),
    amount integer NOT NULL CHECK(amount > 0), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS payments_one_success ON payments(reservation_id)
    WHERE status = 'SUCCEEDED';
CREATE TABLE IF NOT EXISTS bookings (
    id text PRIMARY KEY, reservation_id text NOT NULL UNIQUE,
    session_id text NOT NULL REFERENCES users(session_id),
    status text NOT NULL CHECK(status = 'CONFIRMED'), created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(reservation_id, session_id) REFERENCES reservations(id, session_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tickets (
    id text PRIMARY KEY, booking_id text NOT NULL REFERENCES bookings ON DELETE CASCADE,
    event_id text NOT NULL, seat_id integer NOT NULL,
    UNIQUE(event_id, seat_id), FOREIGN KEY(event_id, seat_id) REFERENCES seats(event_id, id)
);

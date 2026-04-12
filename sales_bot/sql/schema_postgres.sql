CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY,
    added_by BIGINT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS systems (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    image_path TEXT,
    file_path TEXT NOT NULL,
    paypal_link TEXT,
    roblox_gamepass_id TEXT,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_systems (
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    granted_by BIGINT,
    source TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id)
);

CREATE TABLE IF NOT EXISTS delivery_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    source TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blacklist_entries (
    user_id BIGINT PRIMARY KEY,
    display_label TEXT NOT NULL,
    blacklisted_by BIGINT,
    blacklisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blacklist_appeals (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    answer_one TEXT NOT NULL,
    answer_two TEXT NOT NULL,
    owner_message_id BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    reviewed_by BIGINT
);

CREATE TABLE IF NOT EXISTS paypal_purchases (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    paypal_link TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    webhook_payload TEXT
);

CREATE TABLE IF NOT EXISTS vouches (
    id BIGSERIAL PRIMARY KEY,
    admin_user_id BIGINT NOT NULL,
    author_user_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    rating INTEGER NOT NULL,
    posted_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS temp_saved_systems (
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    saved_by BIGINT,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id)
);

CREATE TABLE IF NOT EXISTS transfer_locks (
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    locked_by BIGINT,
    reason TEXT NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roblox_links (
    user_id BIGINT PRIMARY KEY,
    roblox_sub TEXT NOT NULL,
    roblox_username TEXT,
    roblox_display_name TEXT,
    profile_url TEXT,
    raw_profile_json TEXT NOT NULL,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    requested_item TEXT NOT NULL,
    required_timeframe TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    offered_price TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    owner_message_id BIGINT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    reviewed_by BIGINT
);

CREATE INDEX IF NOT EXISTS idx_systems_name ON systems(name);
CREATE INDEX IF NOT EXISTS idx_user_systems_user ON user_systems(user_id);
CREATE INDEX IF NOT EXISTS idx_blacklist_appeals_status ON blacklist_appeals(status);
CREATE INDEX IF NOT EXISTS idx_paypal_purchases_status ON paypal_purchases(status);
CREATE INDEX IF NOT EXISTS idx_vouches_admin_user ON vouches(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_order_requests_status ON order_requests(status);
CREATE INDEX IF NOT EXISTS idx_temp_saved_systems_user ON temp_saved_systems(user_id);
CREATE INDEX IF NOT EXISTS idx_transfer_locks_user ON transfer_locks(user_id);
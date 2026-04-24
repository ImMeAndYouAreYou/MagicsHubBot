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

CREATE TABLE IF NOT EXISTS roblox_gamepass_display_names (
    gamepass_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_assets (
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('file', 'image')),
    asset_name TEXT NOT NULL,
    asset_bytes BYTEA NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (system_id, asset_type)
);

CREATE TABLE IF NOT EXISTS user_systems (
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    granted_by BIGINT,
    source TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id)
);

CREATE TABLE IF NOT EXISTS system_discounts (
    user_id BIGINT NOT NULL,
    system_id BIGINT NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    discount_percent INTEGER NOT NULL,
    created_by BIGINT,
    updated_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
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

CREATE TABLE IF NOT EXISTS roblox_owner_states (
    state TEXT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roblox_owner_links (
    guild_id BIGINT PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    roblox_sub TEXT NOT NULL,
    roblox_username TEXT,
    roblox_display_name TEXT,
    profile_url TEXT,
    raw_profile_json TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    token_expires_at TEXT NOT NULL,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
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

CREATE TABLE IF NOT EXISTS admin_panel_sessions (
    token TEXT PRIMARY KEY,
    admin_user_id BIGINT NOT NULL,
    panel_type TEXT NOT NULL,
    target_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS web_oauth_states (
    state TEXT PRIMARY KEY,
    next_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token TEXT PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    global_name TEXT,
    avatar_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS special_systems (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    payment_methods_json TEXT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,
    created_by BIGINT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS special_system_images (
    id BIGSERIAL PRIMARY KEY,
    special_system_id BIGINT NOT NULL REFERENCES special_systems(id) ON DELETE CASCADE,
    asset_name TEXT NOT NULL,
    content_type TEXT,
    asset_bytes BYTEA NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS special_order_requests (
    id BIGSERIAL PRIMARY KEY,
    special_system_id BIGINT NOT NULL REFERENCES special_systems(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    discord_name TEXT NOT NULL,
    roblox_name TEXT NOT NULL,
    payment_method_key TEXT NOT NULL,
    payment_method_label TEXT NOT NULL,
    payment_price TEXT NOT NULL,
    linked_roblox_sub TEXT,
    linked_roblox_username TEXT,
    linked_roblox_display_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    owner_message_id BIGINT,
    admin_reply TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    reviewed_by BIGINT
);

CREATE TABLE IF NOT EXISTS polls (
    id BIGSERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    result_json TEXT,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS giveaways (
    id BIGSERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,
    title TEXT NOT NULL,
    description TEXT,
    requirements TEXT,
    winner_count INTEGER NOT NULL,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    result_json TEXT,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,
    title TEXT NOT NULL,
    description TEXT,
    reward TEXT NOT NULL,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    winner_user_id BIGINT,
    winner_message_id BIGINT,
    rolled_at TIMESTAMPTZ,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai_knowledge_entries (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    created_by BIGINT,
    source_channel_id BIGINT,
    source_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_training_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    started_by BIGINT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ
);

INSERT INTO ai_training_state (id, is_active)
VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_systems_name ON systems(name);
CREATE INDEX IF NOT EXISTS idx_user_systems_user ON user_systems(user_id);
CREATE INDEX IF NOT EXISTS idx_system_discounts_user ON system_discounts(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_blacklist_appeals_status ON blacklist_appeals(status);
CREATE INDEX IF NOT EXISTS idx_paypal_purchases_status ON paypal_purchases(status);
CREATE INDEX IF NOT EXISTS idx_vouches_admin_user ON vouches(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_order_requests_status ON order_requests(status);
CREATE INDEX IF NOT EXISTS idx_temp_saved_systems_user ON temp_saved_systems(user_id);
CREATE INDEX IF NOT EXISTS idx_transfer_locks_user ON transfer_locks(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_panel_sessions_panel ON admin_panel_sessions(panel_type, expires_at);
CREATE INDEX IF NOT EXISTS idx_web_oauth_states_expires ON web_oauth_states(expires_at);
CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(discord_user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_special_systems_slug ON special_systems(slug);
CREATE INDEX IF NOT EXISTS idx_special_order_requests_status ON special_order_requests(status, submitted_at);
CREATE INDEX IF NOT EXISTS idx_polls_status ON polls(status, ends_at);
CREATE INDEX IF NOT EXISTS idx_giveaways_status ON giveaways(status, ends_at);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status, ends_at);
CREATE INDEX IF NOT EXISTS idx_ai_knowledge_entries_created ON ai_knowledge_entries(created_at);
CREATE INDEX IF NOT EXISTS idx_roblox_links_sub ON roblox_links(roblox_sub);
CREATE INDEX IF NOT EXISTS idx_roblox_owner_states_expires ON roblox_owner_states(expires_at);
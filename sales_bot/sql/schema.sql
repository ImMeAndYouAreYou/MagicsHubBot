PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL,
    image_path TEXT,
    file_path TEXT NOT NULL,
    paypal_link TEXT,
    roblox_gamepass_id TEXT,
    is_visible_on_website BOOLEAN NOT NULL DEFAULT 1,
    is_for_sale BOOLEAN NOT NULL DEFAULT 1,
    is_in_stock BOOLEAN NOT NULL DEFAULT 1,
    website_price TEXT,
    website_currency TEXT NOT NULL DEFAULT 'ILS',
    is_special_system BOOLEAN NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roblox_gamepass_display_names (
    gamepass_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_assets (
    system_id INTEGER NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('file', 'image')),
    asset_name TEXT NOT NULL,
    asset_bytes BLOB NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (system_id, asset_type),
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_gallery_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id INTEGER NOT NULL,
    asset_name TEXT NOT NULL,
    content_type TEXT,
    asset_bytes BLOB NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_systems (
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    granted_by INTEGER,
    source TEXT NOT NULL,
    granted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id),
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_discounts (
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    discount_percent INTEGER NOT NULL,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id),
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS delivery_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS blacklist_entries (
    user_id INTEGER PRIMARY KEY,
    display_label TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    blacklisted_by INTEGER,
    blacklisted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blacklist_appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    answer_one TEXT NOT NULL,
    answer_two TEXT NOT NULL,
    owner_message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    reviewed_by INTEGER
);

CREATE TABLE IF NOT EXISTS paypal_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    paypal_link TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    webhook_payload TEXT,
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vouches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user_id INTEGER NOT NULL,
    author_user_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    rating INTEGER NOT NULL,
    posted_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS temp_saved_systems (
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    saved_by INTEGER,
    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id),
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transfer_locks (
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    locked_by INTEGER,
    reason TEXT NOT NULL,
    locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id),
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roblox_links (
    user_id INTEGER PRIMARY KEY,
    roblox_sub TEXT NOT NULL,
    roblox_username TEXT,
    roblox_display_name TEXT,
    profile_url TEXT,
    raw_profile_json TEXT NOT NULL,
    linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roblox_owner_states (
    state TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roblox_owner_links (
    guild_id INTEGER PRIMARY KEY,
    discord_user_id INTEGER NOT NULL,
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
    linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    requested_item TEXT NOT NULL,
    required_timeframe TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    offered_price TEXT NOT NULL,
    roblox_username TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    owner_message_id INTEGER,
    admin_reply TEXT,
    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    reviewed_by INTEGER
);

CREATE TABLE IF NOT EXISTS order_request_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    asset_name TEXT NOT NULL,
    content_type TEXT,
    asset_bytes BLOB NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES order_requests(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admin_panel_sessions (
    token TEXT PRIMARY KEY,
    admin_user_id INTEGER NOT NULL,
    panel_type TEXT NOT NULL,
    target_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_oauth_states (
    state TEXT PRIMARY KEY,
    next_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token TEXT PRIMARY KEY,
    discord_user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    global_name TEXT,
    avatar_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS website_cart_items (
    user_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, system_id),
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discount_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    discount_type TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT,
    system_id INTEGER,
    max_redemptions INTEGER,
    per_user_limit INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    expires_at TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS website_checkout_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    payment_method TEXT NOT NULL,
    fulfillment_mode TEXT NOT NULL DEFAULT 'self',
    status TEXT NOT NULL DEFAULT 'pending',
    paypal_status TEXT NOT NULL DEFAULT 'not-started',
    paypal_order_id TEXT,
    paypal_capture_id TEXT,
    paypal_approval_url TEXT,
    paypal_payload_json TEXT,
    discount_code_id INTEGER,
    discount_code_text TEXT,
    subtotal_amount TEXT NOT NULL,
    discount_amount TEXT NOT NULL DEFAULT '0.00',
    total_amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    note TEXT,
    reviewed_at TEXT,
    reviewed_by INTEGER,
    completed_at TEXT,
    cancelled_at TEXT,
    cancel_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (discount_code_id) REFERENCES discount_codes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS website_checkout_order_items (
    order_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    system_name TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    line_total TEXT NOT NULL,
    PRIMARY KEY (order_id, system_id),
    FOREIGN KEY (order_id) REFERENCES website_checkout_orders(id) ON DELETE CASCADE,
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS redeem_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    system_id INTEGER,
    issued_to_user_id INTEGER,
    checkout_order_id INTEGER,
    source TEXT NOT NULL DEFAULT 'admin',
    max_redemptions INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    expires_at TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE SET NULL,
    FOREIGN KEY (checkout_order_id) REFERENCES website_checkout_orders(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS redeem_code_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    redeem_code_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    redeemed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (redeem_code_id, user_id),
    FOREIGN KEY (redeem_code_id) REFERENCES redeem_codes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discount_code_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discount_code_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    discount_amount TEXT NOT NULL,
    redeemed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (discount_code_id) REFERENCES discount_codes(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES website_checkout_orders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS website_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link_path TEXT,
    kind TEXT NOT NULL DEFAULT 'general',
    is_read BOOLEAN NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT
);

CREATE TABLE IF NOT EXISTS special_systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    payment_methods_json TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    created_by INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS special_system_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    special_system_id INTEGER NOT NULL,
    asset_name TEXT NOT NULL,
    content_type TEXT,
    asset_bytes BLOB NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (special_system_id) REFERENCES special_systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS special_order_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    special_system_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    discord_name TEXT NOT NULL,
    roblox_name TEXT NOT NULL,
    payment_method_key TEXT NOT NULL,
    payment_method_label TEXT NOT NULL,
    payment_price TEXT NOT NULL,
    linked_roblox_sub TEXT,
    linked_roblox_username TEXT,
    linked_roblox_display_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    owner_message_id INTEGER,
    admin_reply TEXT,
    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    reviewed_by INTEGER,
    FOREIGN KEY (special_system_id) REFERENCES special_systems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    result_json TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    requirements TEXT,
    winner_count INTEGER NOT NULL,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    result_json TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    reward TEXT NOT NULL,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    winner_user_id INTEGER,
    winner_message_id INTEGER,
    rolled_at TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_knowledge_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_by INTEGER,
    source_channel_id INTEGER,
    source_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_training_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    is_active INTEGER NOT NULL DEFAULT 0,
    started_by INTEGER,
    started_at TEXT,
    ended_at TEXT
);

INSERT OR IGNORE INTO ai_training_state (id, is_active) VALUES (1, 0);

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

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
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

CREATE TABLE IF NOT EXISTS order_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    requested_item TEXT NOT NULL,
    required_timeframe TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    offered_price TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    owner_message_id INTEGER,
    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    reviewed_by INTEGER
);

CREATE INDEX IF NOT EXISTS idx_systems_name ON systems(name);
CREATE INDEX IF NOT EXISTS idx_user_systems_user ON user_systems(user_id);
CREATE INDEX IF NOT EXISTS idx_blacklist_appeals_status ON blacklist_appeals(status);
CREATE INDEX IF NOT EXISTS idx_paypal_purchases_status ON paypal_purchases(status);
CREATE INDEX IF NOT EXISTS idx_vouches_admin_user ON vouches(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_order_requests_status ON order_requests(status);

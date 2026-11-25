"""SQLite schema, constraints, connection policy, and version checking."""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    campus_id TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('USER','ADMIN')),
    status TEXT NOT NULL DEFAULT 'NORMAL' CHECK(status IN ('NORMAL','BANNED')),
    verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_tokens (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    created_at REAL NOT NULL,
    used_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    last_activity REAL NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL
);
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    seller_id TEXT NOT NULL REFERENCES accounts(id),
    state TEXT NOT NULL CHECK(state IN
      ('DRAFT','REVIEW','REJECTED','ON_SALE','PENDING','CONFIRMED',
       'OFF_SHELF','VIOLATION','SOLD')),
    content_json TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1,
    content_version INTEGER NOT NULL DEFAULT 0,
    active_restriction INTEGER NOT NULL DEFAULT 0,
    ban_restriction INTEGER NOT NULL DEFAULT 0,
    current_submission_id TEXT,
    published_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS submitted_versions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    content_version INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    submitted_at REAL NOT NULL,
    UNIQUE(product_id, content_version)
);
CREATE TABLE IF NOT EXISTS review_submissions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    version_id TEXT NOT NULL REFERENCES submitted_versions(id),
    status TEXT NOT NULL CHECK(status IN ('PENDING','WITHDRAWN','APPROVED','REJECTED')),
    reviewer_id TEXT REFERENCES accounts(id),
    reason TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    reviewed_at REAL
);
CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    buyer_id TEXT NOT NULL REFERENCES accounts(id),
    seller_id TEXT NOT NULL REFERENCES accounts(id),
    state TEXT NOT NULL CHECK(state IN ('PENDING','CONFIRMED','REJECTED','CANCELLED','COMPLETED')),
    snapshot_json TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at REAL NOT NULL,
    confirmed_at REAL,
    closed_at REAL,
    completed_at REAL,
    closed_by TEXT REFERENCES accounts(id),
    close_reason TEXT NOT NULL DEFAULT '',
    CHECK(buyer_id != seller_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_reservation
    ON reservations(product_id) WHERE state IN ('PENDING','CONFIRMED');
CREATE UNIQUE INDEX IF NOT EXISTS one_completed_reservation
    ON reservations(product_id) WHERE state = 'COMPLETED';
CREATE INDEX IF NOT EXISTS reservations_buyer ON reservations(buyer_id, created_at);
CREATE INDEX IF NOT EXISTS reservations_seller ON reservations(seller_id, created_at);
CREATE INDEX IF NOT EXISTS products_seller ON products(seller_id, state);
CREATE INDEX IF NOT EXISTS products_market ON products(state, published_at);
CREATE TABLE IF NOT EXISTS idempotency (
    actor_id TEXT NOT NULL REFERENCES accounts(id),
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    digest TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(actor_id, operation, request_key)
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT REFERENCES accounts(id),
    actor_role TEXT,
    operation TEXT NOT NULL,
    object_id TEXT,
    before_state TEXT,
    after_state TEXT,
    result TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    private_owner TEXT REFERENCES accounts(id),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_actor ON audit_logs(actor_id, created_at);
CREATE TABLE IF NOT EXISTS violations (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    admin_id TEXT NOT NULL REFERENCES accounts(id),
    reason TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bans (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    admin_id TEXT NOT NULL REFERENCES accounts(id),
    reason TEXT NOT NULL,
    banned_at REAL NOT NULL,
    lifted_by TEXT REFERENCES accounts(id),
    lifted_at REAL
);
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES accounts(id),
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    created_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS reservation_seller_matches
BEFORE INSERT ON reservations
WHEN NEW.seller_id != (SELECT seller_id FROM products WHERE id=NEW.product_id)
BEGIN SELECT RAISE(ABORT, 'reservation seller mismatch'); END;
CREATE TRIGGER IF NOT EXISTS frozen_version
BEFORE UPDATE ON submitted_versions
BEGIN SELECT RAISE(ABORT, 'submitted versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS keep_version
BEFORE DELETE ON submitted_versions
BEGIN SELECT RAISE(ABORT, 'submitted versions must be retained'); END;
CREATE TRIGGER IF NOT EXISTS frozen_snapshot
BEFORE UPDATE OF snapshot_json, buyer_id, seller_id, product_id ON reservations
BEGIN SELECT RAISE(ABORT, 'reservation snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS frozen_audit
BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS keep_audit
BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit log must be retained'); END;
"""


def connect(path):
    """Open a fresh connection; services never share one across threads."""
    connection = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def initialize(path):
    """Create a versioned database without silently migrating unknown schemas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError("数据库版本不兼容，请使用匹配的软件版本")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        connection.close()
    path.chmod(0o600)

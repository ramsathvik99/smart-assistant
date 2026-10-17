-- Migration 015: User API Credentials Storage
-- Provides isolated, encrypted storage for per-user API keys and integration secrets.

CREATE TABLE IF NOT EXISTS user_api_credentials (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(64) NOT NULL,
    encrypted_value TEXT NOT NULL,
    masked_hint VARCHAR(64),
    status VARCHAR(32) DEFAULT 'untested',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_user_api_creds_uid ON user_api_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_api_creds_provider ON user_api_credentials(provider);

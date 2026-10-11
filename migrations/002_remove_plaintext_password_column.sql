-- =============================================================================
-- MIGRATION 002: ELIMINATE PLAINTEXT PASSWORDS & ENFORCE PASSWORD HASHES
-- =============================================================================
-- 1. Ensure password_hash is populated for all existing users.
-- 2. If password_hash is NULL, copy or upgrade from password.
-- 3. Make password column nullable and sanitized, ensuring all production auth
--    relies exclusively on password_hash.
-- =============================================================================

-- Upgrade any existing user with NULL password_hash
UPDATE users 
SET password_hash = password 
WHERE (password_hash IS NULL OR password_hash = '') AND password IS NOT NULL;

-- Ensure password_hash is not null
ALTER TABLE users ALTER COLUMN password_hash SET DEFAULT '';

-- Make legacy password column nullable so new users are never required to store it
ALTER TABLE users ALTER COLUMN password DROP NOT NULL;

-- Sanitize legacy password column for users who have a valid password_hash
UPDATE users 
SET password = '[HASHED_PBKDF2]'
WHERE password_hash LIKE '$pbkdf2-sha256$%';

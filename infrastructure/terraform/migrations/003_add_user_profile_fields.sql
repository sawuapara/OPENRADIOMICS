-- Migration: Add user profile fields for custom registration
-- Version: 3
-- Description: Add HIPAA-compliant profile fields to users table

-- Add profile fields
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20);

-- Add address fields
ALTER TABLE users ADD COLUMN IF NOT EXISTS street_address VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(100);

-- Add consent tracking fields
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hipaa_acknowledged_at TIMESTAMPTZ;

-- Make email nullable (for phone-only registration)
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;

-- Add index for phone lookups
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

-- Record migration
INSERT INTO schema_version (version, description)
VALUES (3, 'Add user profile fields for custom registration (name, phone, address, consent tracking)')
ON CONFLICT (version) DO NOTHING;

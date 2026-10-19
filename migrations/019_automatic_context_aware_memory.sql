-- Migration 019: Automatic Context-Aware Long-Term Memory
-- Extends memory_facts with structured category, confirmation status,
-- source reference, expiration date for temporary events, and supersession links.

ALTER TABLE IF EXISTS memory_facts
    ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'confirmed',
    ADD COLUMN IF NOT EXISTS source_ref TEXT,
    ADD COLUMN IF NOT EXISTS last_confirmed TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS expiration_date TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS superseded_by INTEGER REFERENCES memory_facts(id) ON DELETE SET NULL;

-- Performance indexes for tenant-isolated memory retrieval
CREATE INDEX IF NOT EXISTS idx_memory_facts_user_cat ON memory_facts(user_id, category);
CREATE INDEX IF NOT EXISTS idx_memory_facts_user_status ON memory_facts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_facts_expiration ON memory_facts(expiration_date);

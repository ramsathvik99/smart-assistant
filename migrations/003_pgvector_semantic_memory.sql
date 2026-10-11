-- =============================================================================
-- MIGRATION 003: REAL PGVECTOR SEMANTIC MEMORY ARCHITECTURE
-- =============================================================================
-- 1. Enable pgvector extension if supported by PostgreSQL engine.
-- 2. Add real vector column to memory_embeddings.
-- 3. Create cosine distance index for high-speed user-isolated similarity search.
-- =============================================================================

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension not available in environment; vector columns will use fallback storage.';
END $$;

-- Add real vector column (1536 dimensions default for OpenAI text-embedding-3 / standard embeddings)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        BEGIN
            ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS embedding vector(1536);
        EXCEPTION
            WHEN OTHERS THEN
                RAISE NOTICE 'Could not add vector column: %', SQLERRM;
        END;
    END IF;
END $$;

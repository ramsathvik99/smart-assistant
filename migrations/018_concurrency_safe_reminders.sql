-- Migration 018: Concurrency-Safe Atomic Reminders
-- Safe reconciliation: if identical pending reminders exist from pre-concurrency history,
-- mark the earlier duplicate as notified so no user records or audit history are deleted.
WITH ranked_dups AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY user_id, LOWER(TRIM(task_text)), due_at
               ORDER BY id DESC
           ) as rn
    FROM reminders
    WHERE is_notified = FALSE
)
UPDATE reminders
SET is_notified = TRUE
WHERE id IN (
    SELECT id FROM ranked_dups WHERE rn > 1
);

-- Database-enforced uniqueness guarantee on pending reminders for the same user, task, and due time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_reminders_pending_user_task_due
ON reminders (user_id, LOWER(TRIM(task_text)), due_at)
WHERE (is_notified = FALSE);

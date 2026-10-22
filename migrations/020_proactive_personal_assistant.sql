-- Migration 020: Proactive Personal Assistant
-- Adds support for proactive interaction preferences and milestone tracking

-- Add proactive interaction preferences to user_preferences
-- These will be stored as key-value pairs in the existing user_preferences table
-- No schema changes needed for user_preferences (it already supports arbitrary keys)

-- Example preference keys that will be used:
-- proactive_interactions_enabled (boolean) - Master switch for proactive features
-- proactive_birthdays (boolean) - Enable birthday notifications
-- proactive_anniversaries (boolean) - Enable anniversary notifications
-- proactive_education (boolean) - Enable education milestone notifications
-- proactive_career (boolean) - Enable career milestone notifications
-- proactive_projects (boolean) - Enable project deadline notifications
-- proactive_goals (boolean) - Enable goal checkpoint notifications
-- proactive_commitments (boolean) - Enable commitment reminders
-- proactive_custom_dates (boolean) - Enable custom date notifications
-- quiet_hours_enabled (boolean) - Enable quiet hours
-- quiet_hours_start (time) - Start of quiet hours (e.g., "22:00")
-- quiet_hours_end (time) - End of quiet hours (e.g., "08:00")
-- proactive_notification_channel (text) - Preferred delivery channel ("voice", "ui", "both")
-- proactive_notification_time (time) - Preferred time for daily notifications (e.g., "09:00")

-- Create index for faster preference lookups if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_user_preferences_key ON user_preferences(pref_key);

-- Add milestone notification tracking table
-- This tracks which milestones have been notified to avoid duplicate notifications
CREATE TABLE IF NOT EXISTS milestone_notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    milestone_id VARCHAR(32) NOT NULL,
    milestone_type VARCHAR(50) NOT NULL,
    notification_date DATE NOT NULL,
    notified_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    message TEXT,
    UNIQUE (user_id, milestone_id, notification_date)
);

CREATE INDEX IF NOT EXISTS idx_milestone_notifications_user ON milestone_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_milestone_notifications_date ON milestone_notifications(notification_date);
CREATE INDEX IF NOT EXISTS idx_milestone_notifications_type ON milestone_notifications(milestone_type);

-- Add comment explaining the table
COMMENT ON TABLE milestone_notifications IS 'Tracks proactive milestone notifications to prevent duplicates and enable conversation continuity';

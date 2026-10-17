-- Migration 016: Calendar Subsystem Expansion Schema
-- Adds support for event locations, categories, metadata, recurrence exceptions, working hours, and default reminders.

ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'General';
ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

ALTER TABLE recurrence_rules ADD COLUMN IF NOT EXISTS exceptions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE recurrence_rules ADD COLUMN IF NOT EXISTS count INTEGER;

ALTER TABLE calendar_settings ADD COLUMN IF NOT EXISTS working_hours_start TEXT DEFAULT '09:00';
ALTER TABLE calendar_settings ADD COLUMN IF NOT EXISTS working_hours_end TEXT DEFAULT '18:00';
ALTER TABLE calendar_settings ADD COLUMN IF NOT EXISTS default_reminder_minutes INTEGER DEFAULT 15;

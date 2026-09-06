-- 014_sharing_enum_values.sql
-- Enum additions must commit before later migrations may safely reference them.

ALTER TYPE course_visibility ADD VALUE IF NOT EXISTS 'invite_only';
ALTER TYPE enrollment_status ADD VALUE IF NOT EXISTS 'invited';
ALTER TYPE enrollment_status ADD VALUE IF NOT EXISTS 'declined';
ALTER TYPE enrollment_source ADD VALUE IF NOT EXISTS 'join_code';

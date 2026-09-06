-- 017_canonical_code_format.sql
-- One canonical shareable-code format across the product: 16 characters from
-- a 31-symbol alphabet (look-alikes removed), displayed as
-- XXXX-XXXX-XXXX-XXXX. Both course join codes and premium claim codes adopt
-- it. Existing course codes are regenerated (the format changed; the DB held
-- no real data at migration time). Premium code hashes are format-agnostic
-- (sha256 of the normalized code) and need no data change.

DO $$
DECLARE
    alphabet CONSTANT TEXT := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
    new_code TEXT;
    course_row RECORD;
    i INT;
BEGIN
    FOR course_row IN SELECT course_id FROM courses LOOP
        new_code := '';
        FOR i IN 1..16 LOOP
            new_code := new_code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
        END LOOP;
        UPDATE courses SET code = new_code WHERE course_id = course_row.course_id;
    END LOOP;
END $$;

ALTER TABLE courses
    ADD CONSTRAINT courses_join_code_known
    CHECK (code ~ '^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{16}$');

ALTER TABLE premium_codes
    ADD CONSTRAINT premium_codes_code_hash_hex
    CHECK (code_hash ~ '^[0-9a-f]{64}$');
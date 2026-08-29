-- 004_source_object_consistency.sql
-- A source and its generic course object must describe the same course and
-- creator, not merely reference any valid object ID.

ALTER TABLE course_objects
    ADD CONSTRAINT course_objects_source_identity_unique
    UNIQUE (object_id, course_id, created_by_user_id);

ALTER TABLE sources DROP CONSTRAINT sources_object_fk;

ALTER TABLE sources
    ADD CONSTRAINT sources_object_identity_fk
    FOREIGN KEY (object_id, course_id, uploaded_by_user_id)
    REFERENCES course_objects (object_id, course_id, created_by_user_id)
    ON DELETE CASCADE;

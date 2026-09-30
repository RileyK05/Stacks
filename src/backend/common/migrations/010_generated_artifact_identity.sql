CREATE UNIQUE INDEX idx_artifacts_message_item
ON artifacts(course_id, json_extract(origin, '$.message_id'), json_extract(origin, '$.item_index'))
WHERE json_extract(origin, '$.adopted') = 1;

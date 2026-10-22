-- A story's preview image, as a link to the publisher's own file (og:image,
-- the feed's enclosure, or a YC company logo). Never downloaded or re-hosted.
alter table items
    add column image_url  text check (image_url ~ '^https://' and length(image_url) <= 1000),
    add column image_kind text check (image_kind in ('cover', 'logo'));

-- Synthetic SwiftDrop 1.0.0 database (schema version 1, no connections_per_download setting).
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    ord INTEGER NOT NULL,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE,
    url TEXT NOT NULL,
    dedupe_key TEXT,
    title TEXT,
    source TEXT,
    kind TEXT,
    status TEXT NOT NULL,
    filepath TEXT,
    file_size INTEGER,
    quality TEXT,
    error_code TEXT,
    error_message TEXT,
    thumbnail TEXT,
    collection_title TEXT,
    duration REAL,
    sha256 TEXT,
    finished_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS history_finished ON history(finished_at DESC);
CREATE INDEX IF NOT EXISTS history_key ON history(dedupe_key);
PRAGMA user_version=1;
INSERT INTO settings(key, value) VALUES('max_concurrent', '2'), ('theme', '"dark"');
INSERT INTO jobs(id, ord, data, updated_at) VALUES
 ('job-a', 1, '{"url": "https://example.com/a.mp4", "key": "k-a", "destination": "/tmp/dl", "id": "job-a", "state": "paused", "title": "A"}', 1700000000.0),
 ('job-b', 2, '{"url": "https://example.com/b.mp4", "key": "k-b", "destination": "/tmp/dl", "id": "job-b", "state": "queued", "title": "B"}', 1700000001.0);
INSERT INTO history(job_id, url, dedupe_key, title, source, kind, status, filepath, file_size, finished_at) VALUES
 ('h1', 'https://example.com/1.mp4', 'k1', 'One', 'example.com', 'video', 'completed', '/tmp/dl/1.mp4', 1000, 1700000100.0),
 ('h2', 'https://example.com/2.mp3', 'k2', 'Two', 'example.com', 'audio', 'completed', '/tmp/dl/2.mp3', 2000, 1700000200.0),
 ('h3', 'https://example.com/3.mp4', 'k3', 'Three', 'example.com', 'video', 'failed', NULL, NULL, 1700000300.0);

import json
import sqlite3
from pathlib import Path

from .utils import canonical_url, iso, sha256, utcnow


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                record_type TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                PRIMARY KEY (record_type, canonical_key)
            );
            CREATE TABLE IF NOT EXISTS seen_signals (
                canonical_url TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                published_at TEXT,
                verification_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_checks (
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL,
                candidates_seen INTEGER NOT NULL,
                error_type TEXT,
                PRIMARY KEY (source_type, source_name)
            );
            CREATE TABLE IF NOT EXISTS mapping_log (
                raw_name TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                method TEXT NOT NULL,
                score REAL NOT NULL,
                source_url TEXT NOT NULL,
                UNIQUE(raw_name, canonical_name, source_url)
            );
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(records)")}
        if "raw_payload" not in columns:
            self.db.execute("ALTER TABLE records ADD COLUMN raw_payload TEXT NOT NULL DEFAULT '{}' ")
        self.db.commit()

    def upsert(self, entity, key, evidence):
        if not key or not entity.get("source", {}).get("url"):
            raise ValueError("Record requires stable identity and a real source URL")
        record_type = entity["recordType"]
        if record_type == "PRODUCT":
            previous = self.db.execute(
                "SELECT payload, raw_payload FROM records WHERE record_type='PRODUCT' AND canonical_key=?",
                (key,),
            ).fetchone()
            if previous:
                old_content = json.loads(previous[0]).get("content", {})
                if old_content.get("metadataCheckedAt"):
                    incoming = entity.setdefault("content", {})
                    for field in ("description", "startupName"):
                        if not incoming.get(field) and old_content.get(field):
                            incoming[field] = old_content[field]
                    if old_content.get("titleSource") == "space_card" and old_content.get("productName"):
                        incoming["productName"] = old_content["productName"]
                    for field in ("metadataCheckedAt", "descriptionSource", "ownerVerification", "titleSource"):
                        if field not in incoming and field in old_content:
                            incoming[field] = old_content[field]
                    old_evidence = json.loads(previous[1])
                    if isinstance(evidence, dict) and isinstance(old_evidence, dict):
                        if "_metadata_enrichment" in old_evidence:
                            evidence = dict(evidence)
                            evidence["_metadata_enrichment"] = old_evidence["_metadata_enrichment"]
        payload = json.dumps(entity, ensure_ascii=False, sort_keys=True)
        self.db.execute("""
            INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_type, canonical_key) DO UPDATE SET
                payload=excluded.payload,
                evidence_hash=excluded.evidence_hash,
                collected_at=excluded.collected_at,
                raw_payload=excluded.raw_payload
        """, (record_type, key, payload, sha256(evidence), iso(utcnow()), json.dumps(evidence, ensure_ascii=False, default=str)))
        self.db.commit()

    def insert_verified_signal(self, entity, key, evidence, published_at):
        url = canonical_url(key)
        if not url or not published_at:
            raise ValueError("Verified signal requires canonical URL and publication timestamp")
        payload = json.dumps(entity, ensure_ascii=False, sort_keys=True)
        now = iso(utcnow())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.db.execute("""
                INSERT OR IGNORE INTO seen_signals VALUES (?, ?, ?, ?, 'verified')
            """, (url, now, sha256(evidence), published_at))
            is_new = cursor.rowcount == 1
            if not is_new:
                existing = self.db.execute("SELECT verification_status FROM seen_signals WHERE canonical_url=?", (url,)).fetchone()
                if existing and existing[0] == "uncertain":
                    self.db.execute("UPDATE seen_signals SET published_at=?, verification_status='verified' WHERE canonical_url=?", (published_at, url))
                    is_new = True
            if is_new:
                self.db.execute("""
                    INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_type, canonical_key) DO UPDATE SET
                        payload=excluded.payload, evidence_hash=excluded.evidence_hash,
                        collected_at=excluded.collected_at, raw_payload=excluded.raw_payload
                """, (entity["recordType"], url, payload, sha256(evidence), now, json.dumps(evidence, ensure_ascii=False, default=str)))
            self.db.commit()
            return is_new
        except Exception:
            self.db.rollback()
            raise

    def update_news_enrichment(self, url, fields, status):
        if status not in {"evidence_validated", "failed", "empty"}:
            raise ValueError("Unsupported enrichment status")
        if status == "evidence_validated" and (not isinstance(fields, dict) or not fields):
            raise ValueError("Validated enrichment requires at least one grounded field")
        key = canonical_url(url)
        if not key:
            return False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT payload FROM records WHERE record_type='NEWS' AND canonical_key=?", (key,)
            ).fetchone()
            if not row:
                self.db.rollback()
                return False
            entity = json.loads(row[0])
            entity["content"]["llmExtraction"] = fields if status == "evidence_validated" else None
            entity["content"]["llmExtractionStatus"] = status
            self.db.execute(
                "UPDATE records SET payload=? WHERE record_type='NEWS' AND canonical_key=?",
                (json.dumps(entity, ensure_ascii=False, sort_keys=True), key),
            )
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def update_product_enrichment(self, key, updates, evidence):
        if not updates or not isinstance(evidence, dict):
            return False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT payload, raw_payload FROM records WHERE record_type='PRODUCT' AND canonical_key=?",
                (key,),
            ).fetchone()
            if not row:
                self.db.rollback()
                return False
            record = json.loads(row[0])
            original = dict(record["content"])
            record["content"].update(updates)
            raw = json.loads(row[1])
            if not isinstance(raw, dict):
                raw = {"originalEvidence": raw}
            raw["_metadata_enrichment"] = evidence
            self.db.execute(
                "UPDATE records SET payload=?, raw_payload=?, evidence_hash=? "
                "WHERE record_type='PRODUCT' AND canonical_key=?",
                (json.dumps(record, ensure_ascii=False, sort_keys=True),
                 json.dumps(raw, ensure_ascii=False), sha256(raw), key),
            )
            self.db.commit()
            return original != record["content"]
        except Exception:
            self.db.rollback()
            raise

    def signal_first_seen(self, url, content, published_at, verified):
        url = canonical_url(url)
        if not url:
            return False
        cursor = self.db.execute("""
            INSERT OR IGNORE INTO seen_signals VALUES (?, ?, ?, ?, ?)
        """, (url, iso(utcnow()), sha256(content), published_at, "verified" if verified else "uncertain"))
        self.db.commit()
        return cursor.rowcount == 1

    def mark_source_check(self, source_type, source_name, status, candidates_seen=0, error_type=None):
        self.db.execute("""
            INSERT INTO source_checks VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_name) DO UPDATE SET
                checked_at=excluded.checked_at, status=excluded.status,
                candidates_seen=excluded.candidates_seen, error_type=excluded.error_type
        """, (source_type, source_name, iso(utcnow()), status, candidates_seen, error_type))
        self.db.commit()

    def source_checks(self):
        return [dict(zip(("type", "name", "checkedAt", "status", "candidatesSeen", "errorType"), row))
                for row in self.db.execute("SELECT source_type, source_name, checked_at, status, candidates_seen, error_type FROM source_checks ORDER BY source_type, source_name")]

    def log_mapping(self, raw, canonical, method, score, source_url):
        self.db.execute("INSERT OR IGNORE INTO mapping_log VALUES (?, ?, ?, ?, ?)", (raw, canonical, method, score, source_url))
        self.db.commit()

    def get_records(self, record_type):
        rows = self.db.execute("SELECT payload FROM records WHERE record_type=? ORDER BY canonical_key", (record_type,))
        return [json.loads(row[0]) for row in rows]

    def get_raw_evidence(self, record_type, canonical_key):
        row = self.db.execute("SELECT raw_payload FROM records WHERE record_type=? AND canonical_key=?",
                              (record_type, canonical_key)).fetchone()
        return json.loads(row[0]) if row else None

    def get_mappings(self):
        return list(self.db.execute("SELECT raw_name, canonical_name, method, score, source_url FROM mapping_log ORDER BY canonical_name"))

    def counts(self):
        return dict(self.db.execute("SELECT record_type, COUNT(*) FROM records GROUP BY record_type"))

    def close(self):
        self.db.close()

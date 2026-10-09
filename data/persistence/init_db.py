import os
import sqlite3

DB_PATH = "data/persistence/kikeriki.db"


def init_database(db_path: str = DB_PATH) -> None:
    """Initializes the complete SQLite schema for issues and crops."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")

        # Source and Provenance
        conn.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                issue_id TEXT PRIMARY KEY,
                issue_date TEXT NOT NULL,
                year INTEGER NOT NULL,
                era TEXT NOT NULL,
                liturgical_cycle TEXT NOT NULL,
                feast_date TEXT NOT NULL,
                delta_days INTEGER NOT NULL,
                anno_url TEXT NOT NULL,
                page_count INTEGER,
                harvested_at TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_date ON issues(issue_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_cycle_era ON issues(liturgical_cycle, era);")

        # Modalities (Visual crops and Fraktur captions)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crops (
                crop_id TEXT PRIMARY KEY,
                issue_id TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                crop_type TEXT NOT NULL,
                bbox_x INTEGER NOT NULL,
                bbox_y INTEGER NOT NULL,
                bbox_w INTEGER NOT NULL,
                bbox_h INTEGER NOT NULL,
                crop_path TEXT NOT NULL,
                caption_raw TEXT,
                caption_normalized TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (issue_id) REFERENCES issues (issue_id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crops_issue ON crops(issue_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crops_page ON crops(issue_id, page_number);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crops_type ON crops(crop_type);")

        conn.commit()
        print(f"Database schema verified at: {db_path}")


if __name__ == "__main__":
    init_database()
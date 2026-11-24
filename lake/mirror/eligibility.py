import sqlite3


def prepare_eligibility_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS withdrawn_publications (
            publication_id TEXT PRIMARY KEY, notice_id TEXT NOT NULL UNIQUE
        )
    ''')


def is_publication_withdrawn(db: sqlite3.Connection, publication_id: str) -> bool:
    return db.execute(
        'SELECT 1 FROM withdrawn_publications WHERE publication_id = ?', (publication_id,),
    ).fetchone() is not None


def mark_publication_withdrawn(db: sqlite3.Connection, publication_id: str, notice_id: str) -> str:
    db.execute('''
        INSERT INTO withdrawn_publications VALUES (?, ?)
        ON CONFLICT(publication_id) DO NOTHING
    ''', (publication_id, notice_id))
    row = db.execute(
        'SELECT notice_id FROM withdrawn_publications WHERE publication_id = ?', (publication_id,),
    ).fetchone()
    return row[0]

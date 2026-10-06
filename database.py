import shutil
import sqlite3
from pathlib import Path
from datetime import datetime


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.covers_dir = self.db_path.parent / "covers"
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    cover_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    synopsis TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT 'Você',
                    visibility TEXT NOT NULL DEFAULT 'private'
                )
            """)
            columns = {row[1] for row in con.execute("PRAGMA table_info(books)").fetchall()}
            migrations = {
                "synopsis": "ALTER TABLE books ADD COLUMN synopsis TEXT NOT NULL DEFAULT ''",
                "author": "ALTER TABLE books ADD COLUMN author TEXT NOT NULL DEFAULT 'Você'",
                "visibility": "ALTER TABLE books ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'",
            }
            for name, sql in migrations.items():
                if name not in columns:
                    con.execute(sql)
            con.commit()

    def create_book(self, title: str, text: str, cover_source: Path, synopsis: str = "", author: str = "Você", visibility: str = "private"):
        cover_source = Path(cover_source)
        if not cover_source.exists():
            raise FileNotFoundError(f"A capa não foi encontrada:\n{cover_source}")
        suffix = cover_source.suffix.lower() or ".png"
        visibility = visibility if visibility in {"private", "public", "unlisted"} else "private"
        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO books (title, text, cover_path, created_at, synopsis, author, visibility)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, text, str(cover_source), datetime.now().isoformat(timespec="seconds"), synopsis or "", author or "Você", visibility)
            )
            book_id = cur.lastrowid
            destination = self.covers_dir / f"book_{book_id}{suffix}"
            shutil.copy2(cover_source, destination)
            con.execute("UPDATE books SET cover_path=? WHERE id=?", (str(destination), book_id))
            con.commit()
        return book_id

    def get_books(self):
        with self.connect() as con:
            rows = con.execute("SELECT id, title, text, cover_path, created_at, synopsis, author, visibility FROM books ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_public_books(self):
        with self.connect() as con:
            rows = con.execute("SELECT id, title, text, cover_path, created_at, synopsis, author, visibility FROM books WHERE visibility='public' ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_book(self, book_id: int):
        with self.connect() as con:
            row = con.execute("SELECT id, title, text, cover_path, created_at, synopsis, author, visibility FROM books WHERE id=?", (book_id,)).fetchone()
        return dict(row) if row else None

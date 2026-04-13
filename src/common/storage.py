"""
OCR 처리 결과를 SQLite DB에 저장 및 조회
"""
import sqlite3
import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "ocr_data.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        page_count INTEGER,
        processed_time REAL,
        markdown_path TEXT,
        mode TEXT DEFAULT 'printed'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER,
        page_num INTEGER,
        text_content TEXT,
        image_paths TEXT,
        FOREIGN KEY (document_id) REFERENCES documents (id)
    )
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {DB_PATH}")


def save_document(filename, page_count, processed_time, markdown_path, pages_data, mode="printed"):
    """
    OCR 결과를 DB에 저장

    Args:
        pages_data: [{"page_num": 1, "text": "...", "images": [...]}, ...]
        mode: "printed" 또는 "handwritten"

    Returns:
        document id 또는 None
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO documents (filename, page_count, processed_time, markdown_path, mode) VALUES (?, ?, ?, ?, ?)",
            (filename, page_count, processed_time, markdown_path, mode),
        )

        doc_id = cursor.lastrowid

        for page in pages_data:
            images_json = json.dumps(page.get("images", []), ensure_ascii=False)
            cursor.execute(
                "INSERT INTO pages (document_id, page_num, text_content, image_paths) VALUES (?, ?, ?, ?)",
                (doc_id, page["page_num"], page.get("text", ""), images_json),
            )

        conn.commit()
        print(f"💾 Saved '{filename}' (ID: {doc_id}, mode: {mode})")
        return doc_id

    except Exception as e:
        print(f"❌ DB Error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def get_all_documents():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM documents ORDER BY upload_date DESC")
    rows = cursor.fetchall()

    documents = [dict(row) for row in rows]
    conn.close()
    return documents


def get_document_detail(doc_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        return None

    cursor.execute("SELECT * FROM pages WHERE document_id = ? ORDER BY page_num", (doc_id,))
    pages = [dict(row) for row in cursor.fetchall()]

    result = dict(doc)
    result["pages"] = pages
    conn.close()
    return result

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "attendance.db"


def connect():
    return sqlite3.connect(str(DB_PATH))


def create_tables():
    db = connect()

    try:
        with db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    class_name TEXT,
                    face_encoding BLOB
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT,
                    class_name TEXT,
                    date TEXT,
                    enter_time TEXT
                )
            """)

            student_columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(students)")
            }

            if "class_name" not in student_columns:
                db.execute(
                    "ALTER TABLE students ADD COLUMN class_name TEXT"
                )

            attendance_columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(attendance)")
            }

            if "class_name" not in attendance_columns:
                db.execute(
                    "ALTER TABLE attendance ADD COLUMN class_name TEXT"
                )

            if "enter_time" not in attendance_columns:
                db.execute(
                    "ALTER TABLE attendance ADD COLUMN enter_time TEXT"
                )

                if "time" in attendance_columns:
                    db.execute(
                        "UPDATE attendance SET enter_time = time"
                    )

    finally:
        db.close()


if __name__ == "__main__":
    create_tables()
    print("Database ready:", DB_PATH)
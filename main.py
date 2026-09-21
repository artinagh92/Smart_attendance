import sqlite3
import pickle
from pathlib import Path
from datetime import datetime


import cv2
import numpy as np
import face_recognition



DB_PATH = Path(__file__).resolve().parent / "attendance.db"
THRESHOLD = 0.55


def prepare_database(db):
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


def load_students(db):
    # Extra samples belong to the same student ID.
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS face_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                face_encoding BLOB NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)

    students = []
    known_faces = []

    rows = db.execute("""
        SELECT id, name, class_name, face_encoding
        FROM students

        UNION ALL

        SELECT
            s.id,
            s.name,
            s.class_name,
            f.face_encoding
        FROM face_samples AS f
        JOIN students AS s ON s.id = f.student_id
    """).fetchall()

    for student_id, name, class_name, blob in rows:
        if blob is None:
            continue

        try:
            encoding = np.asarray(
                pickle.loads(blob),
                dtype=np.float64
            )

            if encoding.shape != (128,):
                raise ValueError("Invalid encoding shape")

            if not np.isfinite(encoding).all():
                raise ValueError("Invalid encoding values")

        except Exception as error:
            print(f"Skipped sample for ID {student_id}: {error}")
            continue

        # Multiple samples can point to the same student.
        students.append((student_id, name, class_name or ""))
        known_faces.append(encoding)

    return students, known_faces

def register_student(db, camera):
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS face_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                face_encoding BLOB NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)

    print("\n--- Register or add face samples ---")
    print("For an existing student, enter the SAME name and class.")

    name = input("Student name (English): ").strip()
    class_name = input("Class name: ").strip()

    if not name or not class_name:
        print("Name and class cannot be empty.")
        return False

    matches = db.execute(
        """
        SELECT id FROM students
        WHERE name = ? AND COALESCE(class_name, '') = ?
        """,
        (name, class_name)
    ).fetchall()

    if len(matches) > 1:
        print("Multiple students have this name and class.")
        print("Registration stopped to avoid updating the wrong student.")
        return False

    student_id = matches[0][0] if matches else None

    if student_id is not None:
        print(f"Adding samples to: {name} | ID: {student_id}")
    else:
        print(f"Registering new student: {name}")

    print("Only the selected student should stand in front of the camera.")
    print("SPACE or S: save one sample")
    print("ENTER or ESC: finish")
    print("Capture different views, with and without glasses or mask.")

    saved_count = 0
    last_saved_encoding = None
    status = "SPACE / S: Save | ENTER: Finish"

    try:
        while True:
            ret, frame = camera.read()

            if not ret:
                print("Cannot read camera frame.")
                return saved_count > 0

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb)

            display = frame.copy()

            for top, right, bottom, left in locations:
                cv2.rectangle(
                    display,
                    (left, top),
                    (right, bottom),
                    (0, 255, 255),
                    2
                )

            cv2.putText(
                display,
                f"Saved: {saved_count} | Faces: {len(locations)}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2
            )

            cv2.putText(
                display,
                status,
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 255),
                1
            )

            cv2.imshow("Register Student", display)
            key = cv2.waitKey(1) & 0xFF

            if key in (27, 13, 10):
                print(f"Finished. New samples saved: {saved_count}")
                return saved_count > 0

            if key not in (32, ord("s"), ord("S")):
                continue

            if len(locations) != 1:
                status = "Exactly ONE face needed. Try again."
                print(status)
                continue

            encodings = face_recognition.face_encodings(
                rgb, locations
            )

            if len(encodings) != 1:
                status = "Cannot encode face. Adjust pose / lighting."
                print(status)
                continue

            encoding = np.asarray(
                encodings[0],
                dtype=np.float64
            )

            if (
                encoding.shape != (128,)
                or not np.isfinite(encoding).all()
            ):
                status = "Invalid sample. Try again."
                print(status)
                continue

            # Avoid accidentally saving an identical sample repeatedly.
            if (
                last_saved_encoding is not None
                and np.allclose(
                    encoding,
                    last_saved_encoding,
                    rtol=0,
                    atol=0.000001
                )
            ):
                status = "Same sample. Change your pose slightly."
                continue

            blob = pickle.dumps(encoding)

            with db:
                if student_id is None:
                    result = db.execute(
                        """
                        INSERT INTO students (
                            name,
                            class_name,
                            face_encoding
                        )
                        VALUES (?, ?, ?)
                        """,
                        (name, class_name, blob)
                    )

                    student_id = result.lastrowid

                else:
                    db.execute(
                        """
                        INSERT INTO face_samples (
                            student_id,
                            face_encoding
                        )
                        VALUES (?, ?)
                        """,
                        (student_id, blob)
                    )

            saved_count += 1
            last_saved_encoding = encoding.copy()
            status = f"Saved {saved_count}! Change pose / glasses / mask."

            print(
                f"Saved sample {saved_count} "
                f"for {name} | ID: {student_id}"
            )

    finally:
        cv2.destroyAllWindows()
def run_attendance(db, camera, students, known_faces):
    # Avoid repeated database queries for the same student today.
    checked_today = set()
    active_day = None

    print("\nAttendance started.")
    print("Press ESC in the camera window to exit.")

    while True:
        ret, frame = camera.read()

        if not ret:
            print("Cannot read camera frame.")
            break

        today = datetime.now().date().isoformat()

        if today != active_day:
            checked_today.clear()
            active_day = today

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(
            rgb, locations
        )

        for encoding, location in zip(encodings, locations):
            distances = face_recognition.face_distance(
                known_faces, encoding
            )

            best_match = int(np.argmin(distances))
            distance = float(distances[best_match])

            label = f"Unknown | {distance:.2f}"
            color = (0, 0, 255)

            if distance < THRESHOLD:
                student_id, name, class_name = students[best_match]

                label = f"{name} | {distance:.2f}"
                color = (0, 255, 0)

                if student_id not in checked_today:
                    already = db.execute(
                        """
                        SELECT id FROM attendance
                        WHERE student_name = ?
                          AND COALESCE(class_name, '') = ?
                          AND date = ?
                        LIMIT 1
                        """,
                        (name, class_name, today)
                    ).fetchone()

                    if already is None:
                        with db:
                            db.execute(
                                """
                                INSERT INTO attendance (
                                    student_name,
                                    class_name,
                                    date,
                                    enter_time
                                )
                                VALUES (?, ?, ?, ?)
                                """,
                                (
                                    name,
                                    class_name,
                                    today,
                                    datetime.now().strftime("%H:%M:%S")
                                )
                            )

                        print(
                            f"{name}: Attendance Saved "
                            f"| Distance: {distance:.3f}"
                        )
                    else:
                        print(f"{name}: Already recorded today")

                    checked_today.add(student_id)

            top, right, bottom, left = location

            cv2.rectangle(
                frame,
                (left, top),
                (right, bottom),
                color,
                2
            )

            cv2.putText(
                frame,
                label,
                (left, max(top - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2
            )

        cv2.imshow("Attendance - ESC to exit", frame)

        if cv2.waitKey(1) & 0xFF == 27:
            break


def main():
    db = sqlite3.connect(str(DB_PATH))
    camera = None

    try:
        print("Database:", DB_PATH)
        prepare_database(db)

        students, known_faces = load_students(db)
        print("Registered usable faces:", len(students))

        camera = cv2.VideoCapture(0)

        if not camera.isOpened():
            print("Cannot open camera. Close other camera apps.")
            return

        if not students:
            print("No usable faces found. Register your first student.")

            if not register_student(db, camera):
                print("Registration was not completed.")
                return

        else:
            choice = input(
                "Add a new student? (y/n, Enter = n): "
            ).strip().lower()

            if choice == "y":
                register_student(db, camera)

        students, known_faces = load_students(db)

        if not students:
            print("No usable faces available.")
            return

        run_attendance(db, camera, students, known_faces)

    finally:
        if camera is not None:
            camera.release()

        cv2.destroyAllWindows()
        db.close()


if __name__ == "__main__":
    main()
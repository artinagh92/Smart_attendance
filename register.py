import cv2
import face_recognition
import pickle

from database import connect, create_tables, DB_PATH


def main():
    create_tables()

    name = input("Student name (English): ")
    class_name = input("Class name: ")

    if not name or not class_name:
        print("Name and class are required.")
        return

    camera = cv2.VideoCapture(0)

    try:
        if not camera.isOpened():
            print("Cannot open camera.")
            return

        print("Database:", DB_PATH)
        print("Click the camera window. Press S to save, ESC to cancel.")

        while True:
            ret, frame = camera.read()

            if not ret:
                print("Cannot read camera frame.")
                break

            cv2.imshow("Register - S: Save | ESC: Cancel", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:
                break

            if key not in (ord("s"), ord("S")):
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb)

            if len(locations) != 1:
                print("Exactly one face must be visible. Try again.")
                continue

            encodings = face_recognition.face_encodings(rgb, locations)

            if len(encodings) != 1:
                print("Cannot encode this face. Try again.")
                continue

            db = connect()

            try:
                existing = db.execute(
                    """
                    SELECT id FROM students
                    WHERE name = ? AND class_name = ?
                    """,
                    (name, class_name)
                ).fetchone()

                if existing:
                    print("This name is already registered in this class.")
                    break

                with db:
                    db.execute(
                        """
                        INSERT INTO students
                            (name, class_name, face_encoding)
                        VALUES (?, ?, ?)
                        """,
                        (
                            name,
                            class_name,
                            pickle.dumps(encodings[0])
                        )
                    )

                print(f"Saved! Student: {name} | Class: {class_name}")
                break

            finally:
                db.close()

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
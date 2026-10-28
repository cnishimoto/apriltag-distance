
import cv2
from pathlib import Path
from datetime import datetime

# Configuration
CAMERA_INDEX = 1
SAVE_DIR = Path(__file__).resolve().parent / "pictures"

def main():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)

        # Request 1080p resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    # Check actual camera resolution
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Camera resolution: {width} x {height}")

    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    print("Press SPACE to capture an image.")
    print("Press Q to quit.")

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Error: Could not read frame.")
            break

        cv2.imshow("Camera Capture", frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = SAVE_DIR / f"image_{timestamp}.png"

            if cv2.imwrite(str(filename), frame):
                print(f"Saved: {filename}")
            else:
                print("Error: Failed to save image.")

        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

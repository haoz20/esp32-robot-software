import cv2
import numpy as np

WINDOW_NAME = "autonomy"
cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WINDOW_NAME, 960, 720)

# fake small "camera frame" like the ESP32's, to prove scaling works
small_frame = np.zeros((240, 320, 3), dtype=np.uint8)
cv2.putText(small_frame, "test frame", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

while True:
    cv2.imshow(WINDOW_NAME, small_frame)
    if cv2.waitKey(30) & 0xFF == ord(" "):
        break

cv2.destroyAllWindows()

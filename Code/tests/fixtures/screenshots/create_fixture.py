"""Helper script to generate a synthetic fixture screenshot for integration tests."""
import numpy as np
import cv2
import os

def create_synthetic_screenshot(path: str) -> None:
    """Create a simple 800x600 BGR screenshot with a visible button-like region."""
    img = np.ones((600, 800, 3), dtype=np.uint8) * 200  # light gray background

    # Draw a button rectangle at (300, 250, 200, 50) -> x,y,w,h
    cv2.rectangle(img, (300, 250), (500, 300), (100, 100, 240), -1)  # blue button fill
    cv2.rectangle(img, (300, 250), (500, 300), (50, 50, 180), 2)     # border

    # Put text "安装" on the button
    cv2.putText(img, "Install", (340, 282), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, img)

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "synthetic_800x600.png")
    create_synthetic_screenshot(out)
    print(f"Created: {out}")

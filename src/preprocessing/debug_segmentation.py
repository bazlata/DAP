import os
import cv2
import numpy as np

SAMPLE_IMAGE = "data/raw/pages/kik_19030412/page_001.jpg"
DEBUG_OUTPUT = "data/processed/debug_segmentation.jpg"


def inspect_interior_panels(image_path: str = SAMPLE_IMAGE) -> None:
    if not os.path.exists(image_path):
        print(f"Error: Sample image not found at {image_path}")
        return

    img = cv2.imread(image_path)
    h_img, w_img = img.shape[:2]
    total_area = h_img * w_img

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. Otsu thresholding
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 2. Shave off outer scanner margins (20px border) to disconnect frame lines from the edge
    border_px = 25
    thresh[:border_px, :] = 0
    thresh[-border_px:, :] = 0
    thresh[:, :border_px] = 0
    thresh[:, -border_px:] = 0

    # 3. Morphological closing with an intermediate kernel (15x15) to fuse lines without bridging wide gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    # 4. Use cv2.RETR_CCOMP to retrieve internal 2-level hierarchical contours
    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    debug_img = img.copy()
    candidate_boxes = []

    if hierarchy is not None:
        for idx, cnt in enumerate(contours):
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            area_ratio = area / total_area

            # Filter: discard the whole page (>90%), tiny noise (<5%), or narrow strips
            if 0.05 <= area_ratio <= 0.90 and w > 300 and h > 300:
                candidate_boxes.append((x, y, w, h, area_ratio))

    # Sort candidates by area descending
    candidate_boxes.sort(key=lambda b: b[4], reverse=True)

    print(f"Scan dimensions: {w_img}x{h_img}")
    print(f"Valid interior panels found: {len(candidate_boxes)}")

    for idx, (x, y, w, h, ratio) in enumerate(candidate_boxes, start=1):
        print(f"  [{idx}] Box at (x={x}, y={y}), size={w}x{h} -> {ratio*100:.1f}% of page")
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 3)
        cv2.putText(
            debug_img,
            f"Panel {idx}: {w}x{h} ({ratio*100:.1f}%)",
            (x + 15, y + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )

    os.makedirs(os.path.dirname(DEBUG_OUTPUT), exist_ok=True)
    cv2.imwrite(DEBUG_OUTPUT, debug_img)
    print(f"\nSaved updated diagnostic image to: {DEBUG_OUTPUT}")


if __name__ == "__main__":
    inspect_interior_panels()
import os
import sqlite3
from datetime import datetime
from typing import List, Tuple

import cv2
from PIL import Image

DB_PATH = "data/persistence/kikeriki.db"
RAW_PAGES_DIR = "data/raw/pages"
CROPS_OUTPUT_DIR = "data/processed/crops"


def detect_illustration_boxes(image_path: str, min_area_ratio: float = 0.08) -> List[Tuple[int, int, int, int]]:
    """
    Detects potential illustration frames and woodcut bounding boxes on a page scan
    using adaptive thresholding and rectangular contour filtering.
    """
    img = cv2.imread(image_path)
    if img is None:
        return []

    h_img, w_img = img.shape[:2]
    total_area = h_img * w_img

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Adaptive threshold to isolate ink boundaries and borders
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
    )

    # Morphological close to bridge broken woodcut border lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h

        # Retain prominent panels while discarding tiny vignettes, text columns, or page margins
        if area >= total_area * min_area_ratio and w > 200 and h > 200:
            # Filter out whole-page framing artifacts
            if w >= 0.98 * w_img and h >= 0.98 * h_img:
                continue
            boxes.append((x, y, w, h))

    # Sort bounding boxes top-to-bottom
    boxes.sort(key=lambda b: b[1])
    return boxes


def segment_and_store_page(issue_id: str, page_number: int, db_path: str = DB_PATH) -> int:
    """
    Crops detected illustrations from a page, writes the JPEG crops to disk,
    and records their bounding box coordinates in the crops database table.
    """
    page_filename = f"page_{page_number:03d}.jpg"
    page_path = os.path.join(RAW_PAGES_DIR, issue_id, page_filename)

    if not os.path.exists(page_path):
        print(f"Page scan not found: {page_path}")
        return 0

    boxes = detect_illustration_boxes(page_path)
    if not boxes:
        return 0

    target_issue_dir = os.path.join(CROPS_OUTPUT_DIR, issue_id)
    os.makedirs(target_issue_dir, exist_ok=True)

    with Image.open(page_path) as full_img, sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        saved_count = 0

        for idx, (x, y, w, h) in enumerate(boxes, start=1):
            crop_id = f"{issue_id}_p{page_number:02d}_c{idx:02d}"
            crop_filename = f"{crop_id}.jpg"
            crop_path = os.path.join(target_issue_dir, crop_filename)

            # Crop panel (left, upper, right, lower)
            cropped_img = full_img.crop((x, y, x + w, y + h))
            cropped_img.save(crop_path, quality=95)

            crop_type = "front_page_caricature" if page_number == 1 else "panel"

            cursor.execute("""
                INSERT OR REPLACE INTO crops (
                    crop_id, issue_id, page_number, crop_type,
                    bbox_x, bbox_y, bbox_w, bbox_h,
                    crop_path, caption_raw, caption_normalized, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?);
            """, (
                crop_id,
                issue_id,
                page_number,
                crop_type,
                x, y, w, h,
                crop_path,
                datetime.utcnow().isoformat()
            ))
            saved_count += 1

        conn.commit()

    return saved_count


if __name__ == "__main__":
    # Test layout segmentation on the Easter Sunday 1903 front page
    sample_issue = "kik_19030412"
    count = segment_and_store_page(sample_issue, page_number=1)
    print(f"[{sample_issue}] Front page segmentation completed: {count} crop(s) registered.")
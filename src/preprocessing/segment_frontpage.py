import glob
import os
import sqlite3
from datetime import datetime
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

DB_PATH = "data/persistence/kikeriki.db"
RAW_PAGES_DIR = "data/raw/pages"
CROPS_OUTPUT_DIR = "data/processed/crops"


def compute_projection_splits(image_path: str) -> Optional[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]]:
    """
    Computes horizontal projection density to locate the gutters separating
    the masthead, caricature artwork, and caption block.
    """
    img = cv2.imread(image_path)
    if img is None:
        return None

    h_img, w_img = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Focus on the central content grid (excluding margins)
    x1, x2 = int(w_img * 0.08), int(w_img * 0.92)
    content_binary = thresh[:, x1:x2]
    row_density = np.sum(content_binary, axis=1) / (x2 - x1)

    # Gutter 1: Masthead split (14% - 30% of page height)
    m_start, m_end = int(h_img * 0.14), int(h_img * 0.30)
    masthead_split_y = m_start + int(np.argmin(row_density[m_start:m_end]))

    # Gutter 2: Caption split (78% - 93% of page height)
    c_start, c_end = int(h_img * 0.78), int(h_img * 0.93)
    caption_split_y = c_start + int(np.argmin(row_density[c_start:c_end]))

    bottom_margin_y = int(h_img * 0.96)

    caricature_bbox = (x1, masthead_split_y, x2 - x1, caption_split_y - masthead_split_y)
    caption_bbox = (x1, caption_split_y, x2 - x1, bottom_margin_y - caption_split_y)

    return caricature_bbox, caption_bbox


def process_frontpage(issue_id: str, db_conn: sqlite3.Connection) -> int:
    """Segments page 1 of an issue, exports image crops, and logs records to SQLite."""
    page_path = os.path.join(RAW_PAGES_DIR, issue_id, "page_001.jpg")
    if not os.path.exists(page_path):
        return 0

    splits = compute_projection_splits(page_path)
    if not splits:
        return 0

    caricature_bbox, caption_bbox = splits
    out_dir = os.path.join(CROPS_OUTPUT_DIR, issue_id)
    os.makedirs(out_dir, exist_ok=True)

    pil_img = Image.open(page_path)
    now = datetime.utcnow().isoformat()

    # 1. Caricature crop
    caricature_crop_id = f"{issue_id}_p01_c01"
    caricature_rel_path = os.path.join(out_dir, f"{caricature_crop_id}.jpg")
    pil_img.crop((
        caricature_bbox[0], caricature_bbox[1],
        caricature_bbox[0] + caricature_bbox[2], caricature_bbox[1] + caricature_bbox[3]
    )).save(caricature_rel_path, quality=95)

    # 2. Caption crop
    caption_crop_id = f"{issue_id}_p01_cap01"
    caption_rel_path = os.path.join(out_dir, f"{caption_crop_id}.jpg")
    pil_img.crop((
        caption_bbox[0], caption_bbox[1],
        caption_bbox[0] + caption_bbox[2], caption_bbox[1] + caption_bbox[3]
    )).save(caption_rel_path, quality=95)

    cursor = db_conn.cursor()
    # Insert primary caricature entry
    cursor.execute("""
        INSERT OR REPLACE INTO crops (
            crop_id, issue_id, page_number, crop_type,
            bbox_x, bbox_y, bbox_w, bbox_h,
            crop_path, caption_raw, caption_normalized, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?);
    """, (
        caricature_crop_id, issue_id, 1, "front_page_caricature",
        caricature_bbox[0], caricature_bbox[1], caricature_bbox[2], caricature_bbox[3],
        caricature_rel_path, now
    ))

    # Insert separate caption crop entry
    cursor.execute("""
        INSERT OR REPLACE INTO crops (
            crop_id, issue_id, page_number, crop_type,
            bbox_x, bbox_y, bbox_w, bbox_h,
            crop_path, caption_raw, caption_normalized, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?);
    """, (
        caption_crop_id, issue_id, 1, "front_page_caption",
        caption_bbox[0], caption_bbox[1], caption_bbox[2], caption_bbox[3],
        caption_rel_path, now
    ))

    return 2


def batch_segment_frontpages() -> None:
    issue_dirs = sorted(glob.glob(os.path.join(RAW_PAGES_DIR, "kik_*")))
    print(f"Starting front page segmentation for {len(issue_dirs)} issues...")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        total_crops = 0
        for path in issue_dirs:
            issue_id = os.path.basename(path)
            crops_added = process_frontpage(issue_id, conn)
            total_crops += crops_added
            print(f"  [{issue_id}] Registered {crops_added} crops.")
        conn.commit()

    print(f"\nSegmentation complete: {total_crops} total crops registered in {DB_PATH}.")


if __name__ == "__main__":
    batch_segment_frontpages()
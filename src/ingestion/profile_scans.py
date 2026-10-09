# src/ingestion/profile_scans.py
import glob
import os
from PIL import Image
import pandas as pd

PAGES_DIR = "data/raw/pages"

def inspect_corpus(base_dir: str = PAGES_DIR) -> pd.DataFrame:
    """Scans all downloaded JPEG images to extract dimensions, aspect ratios, and color modes."""
    records = []
    image_paths = sorted(glob.glob(os.path.join(base_dir, "*", "*.jpg")))
    
    if not image_paths:
        print(f"No scan images found under {base_dir}")
        return pd.DataFrame()

    for path in image_paths:
        parts = path.split(os.sep)
        issue_id = parts[-2]
        filename = parts[-1]
        file_size_kb = os.path.getsize(path) / 1024

        with Image.open(path) as img:
            width, height = img.size
            records.append({
                "issue_id": issue_id,
                "page": filename,
                "width": width,
                "height": height,
                "megapixels": round((width * height) / 1_000_000, 2),
                "aspect_ratio": round(height / width, 2),
                "mode": img.mode,
                "format": img.format,
                "size_kb": round(file_size_kb, 1),
                "path": path,
            })

    return pd.DataFrame(records)

if __name__ == "__main__":
    df = inspect_corpus()
    if not df.empty:
        print(f"--- Corpus Summary ({len(df)} total pages) ---")
        print(f"Width range:        {df['width'].min()}px - {df['width'].max()}px (mean: {int(df['width'].mean())}px)")
        print(f"Height range:       {df['height'].min()}px - {df['height'].max()}px (mean: {int(df['height'].mean())}px)")
        print(f"Mean file size:     {int(df['size_kb'].mean())} KB")
        print(f"Color modes:        {df['mode'].value_counts().to_dict()}")
        
        print("\n--- Benchmark Holiday Front Pages (page_001.jpg) ---")
        targets = ["kik_19030412", "kik_19030531", "kik_19031224"]
        sample_df = df[df["issue_id"].isin(targets) & (df["page"] == "page_001.jpg")]
        print(sample_df[["issue_id", "width", "height", "megapixels", "mode", "size_kb"]].to_string(index=False))
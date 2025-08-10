import os
import json

# Path to your lessons_progress.json
PROGRESS_FILE = os.path.join(
    os.path.dirname(__file__),
    "lessons_progress.json"
)

def normalize_filepaths():
    if not os.path.exists(PROGRESS_FILE):
        print("❌ lessons_progress.json not found.")
        return
    
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("❌ Error: lessons_progress.json is corrupted.")
            return

    if not isinstance(data, list):
        print("❌ Unexpected file format.")
        return
    
    updated = False
    for entry in data:
        if "filepath" in entry:
            abs_path = os.path.abspath(entry["filepath"])
            if entry["filepath"] != abs_path:
                entry["filepath"] = abs_path
                updated = True
    
    if updated:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print("✅ All filepaths normalized to absolute paths.")
    else:
        print("ℹ No changes were necessary. All filepaths already normalized.")

if __name__ == "__main__":
    normalize_filepaths()

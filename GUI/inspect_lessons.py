import os
import json
from collections import defaultdict
from tinydb import TinyDB

def extract_structure(db_path):
    db = TinyDB(db_path)
    lessons = db.all()

    # Structure: { (level, lesson_type): [list of lesson dicts] }
    grouped = defaultdict(list)
    for entry in lessons:
        level = entry.get('level', 'Unknown')
        lesson_type = entry.get('lesson_type', 'Unknown')
        filepath = entry.get('filepath')
        if filepath and os.path.isfile(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lesson_data = json.load(f)
                    grouped[(level, lesson_type)].append(lesson_data)
            except Exception as e:
                print(f"Error reading lesson file {filepath}: {e}")

    # Print summary per group
    for (level, lesson_type), lessons_list in grouped.items():
        print(f"\n=== Level: {level} | Lesson Type: {lesson_type} ===")
        all_keys = set()
        for lesson in lessons_list:
            all_keys.update(lesson.keys())

        print(f"Keys found in lessons ({len(lessons_list)} samples): {sorted(all_keys)}")

        # Show first lesson sample pretty printed (keys & example values)
        sample = lessons_list[0]
        print("Sample data snippet:")
        for k in sorted(sample.keys()):
            v = sample[k]
            # truncate long strings for readability
            if isinstance(v, str) and len(v) > 80:
                v = v[:77] + "..."
            print(f"  {k}: {v}")
        print("-" * 50)


if __name__ == "__main__":
    db_path = "/home/robinglory/Desktop/Thesis/english_lessons/B1 Level (Intermediate)/Grammar/Future forms Will, be going to, present continuous.json"  # or your raw.json file path
    extract_structure(db_path)

import json
import os
from tinydb import TinyDB

# Define paths
json_path = r"/home/robinglory/Desktop/AIProjects/Thesis/english_lessons/A2 Level (Pre-Intermediate)/Grammar/Asking questions in English: Question forms.json"
tinydb_path = r"/home/robinglory/Desktop/AIProjects/Thesis/english_lessons/TinyDB A2 Level (Pre-Intermediate)/Asking questions in English: Question forms_db.json"

# Create directory if needed
os.makedirs(os.path.dirname(tinydb_path), exist_ok=True)

# Load JSON
with open(json_path, 'r', encoding='utf-8') as f:
    lessons = json.load(f)

# Check and fix structure
if isinstance(lessons, dict):
    lessons = [lessons]

# Save to TinyDB
db = TinyDB(tinydb_path)
db.insert_multiple(lessons)

print("✅ Lessons successfully added to TinyDB!")

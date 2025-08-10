from tinydb import TinyDB, Query
from datetime import datetime
import os
import json

class StudentManager:
    CONVERSATIONS_PATH = 'conversations.json'  # Conversation history storage file

    def __init__(self, lesson_manager=None, db_path='students.json'):
        """
        Enhanced Student Manager with:
        - Better error handling
        - Data validation
        - Backup system
        - Conversation history management
        """
        self.db_path = db_path
        self.db = TinyDB(db_path)
        self.current_user = None
        self.lesson_manager = lesson_manager
        self.conversation_history = []
        self._ensure_default_fields()
        self.lesson_manager = lesson_manager

    def _ensure_default_fields(self):
        """Ensure all student records have required fields"""
        Student = Query()
        for student in self.db.all():
            updates = {}
            if 'progress' not in student:
                updates['progress'] = {
                    'reading': 0.0,
                    'grammar': 0.0,
                    'vocabulary': 0.0
                }
            if 'completed_lessons' not in student:
                updates['completed_lessons'] = []
            if 'created_at' not in student:
                updates['created_at'] = datetime.now().isoformat()
            
            if updates:
                self.db.update(updates, Student.name == student['name'])

    def get_student(self, name):
        """Get student with validation and case-insensitive search"""
        if not name or not isinstance(name, str):
            return None

        Student = Query()
        results = self.db.search(Student.name.matches(name, flags=2))  # 2 = re.IGNORECASE
        if results:
            student = results[0]
            student['progress'] = student.get('progress', {})
            for lesson_type in ['reading', 'grammar', 'vocabulary']:
                if lesson_type not in student['progress']:
                    student['progress'][lesson_type] = 0.0
            return student
        return None

    def update_progress(self, lesson_type, progress_delta=0.1, max_cap=1.0):
        """Update progress with safeguards"""
        if not self.current_user or lesson_type not in ['reading', 'grammar', 'vocabulary']:
            return False

        try:
            Student = Query()
            progress = self.current_user.setdefault('progress', {})
            current = progress.get(lesson_type, 0)
            new_progress = min(round(current + progress_delta, 2), max_cap)

            success = self.db.update(
                {'progress': {**progress, lesson_type: new_progress}},
                Student.name == self.current_user['name']
            )
            
            if success:
                self.current_user['progress'][lesson_type] = new_progress
                return True
            return False
        except Exception as e:
            print(f"Progress update failed: {str(e)}")
            return False

    def complete_lesson(self, lesson_path):
        """Record completed lesson with path validation"""
        if not self.current_user or not isinstance(lesson_path, str):
            return False

        try:
            Student = Query()
            completed = self.current_user.setdefault('completed_lessons', [])
            
            if lesson_path not in completed:
                completed.append(lesson_path)
                success = self.db.update(
                    {'completed_lessons': completed},
                    Student.name == self.current_user['name']
                )
                if success:
                    self.current_user['completed_lessons'] = completed
                    return True
            return False
        except Exception as e:
            print(f"Lesson completion failed: {str(e)}")
            return False
    def sync_progress_with_completed(self):
        """
        Sync current_user['progress'] percentages based on completed lessons
        and total lessons available for each lesson type.
        """
        if not self.current_user:
            return

        user = self.current_user
        lesson_types = ['reading', 'grammar', 'vocabulary']

        for lt in lesson_types:
            # Count completed lessons for this type from current_user completed lessons
            completed_count = 0
            for path in user.get('completed_lessons', []):
                # Ensure path corresponds to this lesson type folder
                if f"/{lt.capitalize()}/" in path or f"\\{lt.capitalize()}\\" in path:
                    completed_count += 1
            
            # Count total lessons in lesson_manager folder for this level and type
            folder = os.path.join(
                self.lesson_manager.lessons_root,
                f"{user['level']} Level (Pre-Intermediate)" if user['level'] == "A2" else f"{user['level']} Level (Intermediate)",
                lt.capitalize()
            )
            total_lessons = len([f for f in os.listdir(folder) if f.endswith('.json')]) if os.path.isdir(folder) else 0

            progress = completed_count / total_lessons if total_lessons > 0 else 0

            # Update both in-memory and DB
            user['progress'][lt] = round(progress, 2)

        # Update progress in DB
        Student = Query()
        self.db.update({'progress': user['progress']}, Student.name == user['name'])

    def backup_database(self, backup_dir='backups'):
        """Create timestamped backup of student data"""
        try:
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f'students_{timestamp}.json')
            
            with open(self.db_path, 'r') as src, open(backup_path, 'w') as dst:
                json.dump(json.load(src), dst)
            return True
        except Exception as e:
            print(f"Backup failed: {str(e)}")
            return False

    def get_student_progress(self, name):
        """Get formatted progress report"""
        student = self.get_student(name)
        if not student:
            return None
            
        return {
            'name': student['name'],
            'level': student['level'],
            'progress': student['progress'],
            'completed_lessons': len(student.get('completed_lessons', [])),
            'created_at': student.get('created_at', 'Unknown')
        }
    
    ### New Conversation History Methods ###

    def load_conversation(self, user_name, lesson_path):
        """Load conversation history for user and lesson from JSON file."""
        if not os.path.exists(self.CONVERSATIONS_PATH):
            return []

        try:
            with open(self.CONVERSATIONS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get(user_name, {}).get(lesson_path, [])
        except Exception as e:
            print(f"Error loading conversation: {e}")
            return []

    def save_conversation(self, user_name, lesson_path, conversation_history):
        """Save conversation history for user and lesson to JSON file."""
        data = {}
        if os.path.exists(self.CONVERSATIONS_PATH):
            try:
                with open(self.CONVERSATIONS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error reading conversations file: {e}")

        if user_name not in data:
            data[user_name] = {}

        data[user_name][lesson_path] = conversation_history

        try:
            with open(self.CONVERSATIONS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving conversation: {e}")
            return False

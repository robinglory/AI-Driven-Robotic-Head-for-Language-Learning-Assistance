from datetime import datetime

class StudentManager:
    def __init__(self):
        self.students = {
            "yan naing kyaw tint": {
                "level": "A2",
                "name": "Yan Naing Kyaw Tint",
                "last_visited": "2025-6-22",
                "progress": {"vocabulary": 0.4, "grammar": 0.2, "reading": 0.6}
            },
            "ngwe thant sin": {
                "level": "B1",
                "name": "Ngwe Thant Sin",
                "last_visited": "2023-11-15",
                "progress": {"vocabulary": 0.4, "grammar": 0.2}
            },
            "wai yan aung": {
                "level": "B1",
                "name": "Wai Yan Aung",
                "last_visited": "2023-11-20",
                "progress": {"reading": 0.7, "vocabulary": 0.5}
            },
            "aye mrat san": {
                "level": "A2",
                "name": "Aye Mrat San",
                "last_visited": "2023-11-18",
                "progress": {"grammar": 0.3, "reading": 0.6}
            }
        }
        self.current_user = None
        self.current_lesson = {}
        self.current_topic = None
        self.conversation_history = []

    def get_student(self, name):
        return self.students.get(name.lower())
    
    def update_progress(self, lesson_type):
        if self.current_user and self.current_lesson:
            self.current_user['progress'][lesson_type.lower()] = (
                self.current_user['progress'].get(lesson_type.lower(), 0) + 0.1
            )
            self.current_user['last_visited'] = datetime.now().strftime("%Y-%m-%d")
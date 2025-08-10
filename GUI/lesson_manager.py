import os
import json
import random
from tinydb import TinyDB, Query
from tkinter import messagebox
from datetime import datetime
import re

class LessonManager:
    GREETINGS = [
        "It's wonderful to see you again, {name}!",
        "Welcome back, {name}! Ready to continue our English journey?",
        "Hello there, {name}! I've been looking forward to our session today.",
        "{name}! How have you been since our last lesson?",
        "Ah, {name}! Perfect timing for our English practice."
    ]

    ENCOURAGEMENTS = [
        "Great choice!",
        "Excellent selection!",
        "That's a wonderful topic to focus on!",
        "I think you'll really enjoy this lesson.",
        "Perfect! Let's dive into this together."
    ]

    def __init__(self, llm_handler=None, lessons_root="/home/robinglory/Desktop/Thesis/english_lessons"):
        self.llm = llm_handler  # For the new LLM integration
        self.lessons_db = TinyDB('lessons_progress.json')
        self.conversation_db = TinyDB('conversations.json')
        self.lessons_root = lessons_root

    def get_lesson_by_type(self, user_level, lesson_type, current_user):
        try:
            folder = os.path.join(
                self.lessons_root,
                f"{user_level} Level (Pre-Intermediate)" if user_level == "A2" 
                else f"{user_level} Level (Intermediate)", 
                lesson_type.capitalize()
            )
            
            if not os.path.isdir(folder):
                messagebox.showerror("Error", f"Directory not found: {folder}")
                return None
            
            files = sorted([f for f in os.listdir(folder) if f.endswith(".json")])
            if not files:
                messagebox.showerror("Error", f"No lesson files found in {folder}")
                return None
            
            Lesson = Query()
            user_lessons = self.lessons_db.search(
                (Lesson.user == current_user['name']) & 
                (Lesson.lesson_type == lesson_type)
            )
            
            completed_lessons = [l['filepath'] for l in user_lessons]
            
            for file in files:
                filepath = os.path.join(folder, file)
                if filepath not in completed_lessons:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lesson = json.load(f)
                        lesson['filepath'] = filepath
                        lesson['level'] = user_level
                        lesson['type'] = lesson_type
                        return lesson
            
            filepath = os.path.join(folder, files[-1])
            with open(filepath, "r", encoding="utf-8") as f:
                lesson = json.load(f)
                lesson['filepath'] = filepath
                lesson['level'] = user_level
                lesson['type'] = lesson_type
                return lesson
            
        except Exception as e:
            messagebox.showerror("Error", f"Error loading lesson: {str(e)}")
            return None
        
    def get_lesson_by_filepath(self, filepath):
        try:
            if not os.path.isfile(filepath):
                return None
            with open(filepath, "r", encoding="utf-8") as f:
                lesson = json.load(f)
            lesson['filepath'] = filepath
            # Infer lesson type from folder name (assuming standard folder structure)
            parts = filepath.split(os.sep)
            if len(parts) >= 2:
                lesson_type = parts[-2].lower()
                lesson['type'] = lesson_type
            return lesson
        except Exception as e:
            print(f"Error reading lesson file {filepath}: {e}")
            return None


    def record_lesson_completion(self, user_name, lesson_data):
        self.lessons_db.insert({
            'user': user_name,
            'lesson_type': lesson_data['type'],
            'level': lesson_data['level'],
            'filepath': lesson_data['filepath'],
            'title': lesson_data.get('title', ''),
            'completed_at': datetime.now().isoformat()
        })

    def save_conversation(self, user_name, lesson_type, conversation):
        self.conversation_db.insert({
            'user': user_name,
            'lesson_type': lesson_type,
            'conversation': conversation,
            'timestamp': datetime.now().isoformat()
        })

    import re

    def ask_lingo(self, question, current_user, current_lesson, conversation_history):
        # Handle exit commands from user
        exit_phrases = ["quit", "exit", "bye", "that's all for today"]
        if question.lower().strip() in exit_phrases:
            if current_lesson:
                self.record_lesson_completion(current_user['name'], current_lesson)
                self.save_conversation(
                    current_user['name'],
                    current_lesson['type'],
                    conversation_history
                )
            return random.choice([
                "It was a pleasure teaching you today!",
                "Great work today! I'm proud of your progress.",
                "Wonderful session! Let's continue next time.",
                "You're doing amazing! Until next time."
            ])

        # Prepare AI message
        full_message = self._prepare_full_message(current_user, current_lesson, question)

        try:
            if not self.llm:
                raise ValueError("LLM handler not initialized")
                
            response = self.llm.get_ai_response(
                message=full_message,
                conversation_history=conversation_history
            )

            # Update conversation history
            conversation_history.append({"role": "user", "content": question})
            conversation_history.append({"role": "assistant", "content": response})

            # --- Robust detection of lesson completion ---
            # Lowercase for easier matching
            resp_lower = response.lower()

            # Keywords that suggest a lesson is over
            completion_keywords = [
                "lesson is finished",
                "lesson finished",
                "lesson complete",
                "lesson completed",
                "we have completed the lesson",
                "that concludes",
                "this concludes",
                "we are done with",
                "end of the lesson",
                "great job today",
                "good job today",
                "session is over",
                "all done for today",
                "bye",
                "Bye"
            ]

            # Check if any keyword is present OR if it matches a regex like "lesson.*(finished|complete)"
            keyword_match = any(kw in resp_lower for kw in completion_keywords)
            regex_match = re.search(r"(lesson|session).*(finished|complete|conclude|over)", resp_lower)

            if keyword_match or regex_match:
                if current_lesson:
                    self.record_lesson_completion(current_user['name'], current_lesson)
                    self.save_conversation(
                        current_user['name'],
                        current_lesson['type'],
                        conversation_history
                    )

            return response

        except Exception as e:
            print(f"AI communication error: {str(e)}")
            return "I'm having some technical difficulties. Could you please rephrase your question?"


    def _prepare_full_message(self, current_user, current_lesson, question):
        """Combine all context into a single message string"""
        context_lines = [
            f"STUDENT: {current_user['name']}",
            f"LEVEL: {current_user['level']}",
            f"LESSON: {current_lesson.get('title', '')}",
            f"TYPE: {current_lesson.get('type', '').upper()}",
            f"OBJECTIVE: {current_lesson.get('objective', '')}",
            f"CONTENT: {current_lesson.get('text', '')[:300]}...",
            "",
            f"QUESTION: {question}"
        ]
        return "\n".join(context_lines)

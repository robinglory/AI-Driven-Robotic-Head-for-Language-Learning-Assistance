import os
import json
import random
from api_manager import APIManager

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

    def __init__(self):
        self.api_manager = APIManager()

    def get_lesson_by_type(self, user_level, lesson_type):
        try:
            root = "/home/robinglory/Desktop/AI Projects/Thesis/english_lessons"
            folder = os.path.join(
                root,
                f"{user_level} Level (Pre-Intermediate)" if user_level == "A2"
                else f"{user_level} Level (Intermediate)",
                lesson_type.capitalize()
            )
            
            if not os.path.isdir(folder):
                return None
            
            files = [f for f in os.listdir(folder) if f.endswith(".json")]
            if not files:
                return None
            
            progress = self.current_user['progress'].get(lesson_type.lower(), 0)
            lesson_index = min(int(progress * len(files)), len(files)-1)
            filepath = os.path.join(folder, files[lesson_index])
            
            with open(filepath, "r", encoding="utf-8") as f:
                lesson = json.load(f)
                lesson['filepath'] = filepath
                return lesson
            
        except Exception as e:
            print(f"Error loading lesson: {str(e)}")
            return None

    def ask_lingo(self, question, current_user, current_lesson, conversation_history):
        if question.lower() in ["quit", "exit", "bye", "that's all for today"]:
            return random.choice([
                "It was a pleasure teaching you today!",
                "Great work today! I'm proud of your progress.",
                "Wonderful session! Let's continue next time.",
                "You're doing amazing! Until next time."
            ])

        # Prepare context
        context = []
        
        if current_lesson:
            context.append(f"Current Lesson: {current_lesson.get('title', '')}")
            if 'objective' in current_lesson:
                context.append(f"Lesson Objective: {current_lesson['objective']}")
            if 'text' in current_lesson:
                context.append(f"Key Content: {current_lesson['text'][:200]}...")
        
        context.append(f"Student Level: {current_user['level']}")
        context.append(f"Student Name: {current_user['name']}")
        
        if current_user['progress']:
            progress_str = ", ".join([f"{k}: {int(v*100)}%" for k,v in current_user['progress'].items()])
            context.append(f"Student Progress: {progress_str}")
        
        context.append(f"Student Question: {question}")
        
        # Build messages
        messages = [
            {"role": "system", "content": "You are Lingo, a friendly, patient English teaching AI. "
             "You teach English to non-native speakers. Be warm, encouraging, and engaging. "
             "Adapt to the student's level. Ask questions to check understanding. "
             "Use the lesson content but don't just recite it - explain clearly. "
             "Keep responses under 4 sentences unless explaining complex concepts."}
        ]
        
        messages.extend(conversation_history[-4:])
        messages.append({"role": "user", "content": "\n".join(context)})
        
        try:
            try:
                response = self.api_manager.client.chat.completions.create(
                    model=self.api_manager.current_model,
                    messages=messages,
                    max_tokens=150,
                    temperature=0.8,
                )
                reply = response.choices[0].message.content.strip()
                conversation_history.append({"role": "assistant", "content": reply})
                return reply

            except Exception as e:
                if "invalid_api_key" in str(e).lower() or "unauthorized" in str(e).lower():
                    self.api_manager.switch_to_backup()
                    return self.ask_lingo(question, current_user, current_lesson, conversation_history)

                return f"I'm having trouble thinking right now. Could you try asking again? ({str(e)})"
            
        except Exception as e:
            return f"I'm having trouble thinking right now. Could you try asking again? ({str(e)})"
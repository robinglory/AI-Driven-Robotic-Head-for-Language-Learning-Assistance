import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from styles import configure_styles
from tkinter import font as tkfont
import random
from datetime import datetime
import json
import os
from api_manager import APIManager  # <-- Add this import

# Helper functions to load/save JSON safely
def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

class LessonScreen:
    STUDENTS_JSON_PATH = "/home/robinglory/Desktop/Thesis/GUI/students.json"
    CONVERSATIONS_JSON_PATH = "/home/robinglory/Desktop/Thesis/GUI/conversations.json"
    
    def __init__(self, root, main_app, student_manager, lesson_type):
        self.root = root
        self.main_app = main_app
        self.student_manager = student_manager
        self.lesson_type = lesson_type
        self.current_lesson = main_app.current_lesson  # Use the lesson from main app
        
        self.llm = APIManager()
        # Identify user and lesson key for saving data
        self.user_id = str(self.student_manager.current_user.get("id", "default"))
        self.lesson_path = self.current_lesson.get('filepath', f"default_{lesson_type}")

        # Load persisted data
        self.conversation_data = load_json(self.CONVERSATIONS_JSON_PATH)
        self.students_data = load_json(self.STUDENTS_JSON_PATH)

        # Load conversation history or start fresh
        self.conversation_history = self.conversation_data.get(self.user_id, {}).get(self.lesson_path, [])
        
        # Sync conversation history with student_manager for consistent updates
        self.student_manager.conversation_history = self.conversation_history
        
        # Window configuration
        self.root.title(f"Lingo - AI Personal English Teacher ({lesson_type.capitalize()} Section)")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg="#f8f9fa")
        
        # Font configuration
        self.title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.content_font = tkfont.Font(family="Segoe UI", size=12)
        self.message_font = tkfont.Font(family="Segoe UI", size=11)
        
        configure_styles()
        self.create_widgets()
        self.load_lesson()
        
    def create_widgets(self):
        """Create GUI elements"""
        main_frame = ttk.Frame(self.root, padding=(20, 15))
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        header_frame = ttk.Frame(main_frame, style="Header.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 20), ipady=10)
        
        ttk.Label(
            header_frame,
            text=f"Lingo - AI Personal English Teacher ({self.lesson_type.capitalize()} Section)",
            style="Header.TLabel"
        ).pack(side=tk.LEFT, padx=10)
        
        back_btn = ttk.Button(
            header_frame,
            text="◄ Back to Dashboard",
            command=self.return_to_dashboard,
            style="Accent.TButton"
        )
        back_btn.pack(side=tk.RIGHT, padx=10)
        
        self.conversation_display = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            font=self.content_font,
            height=30,
            padx=15,
            pady=15,
            state='disabled',
            bg="white",
            fg="#2d3436",
            bd=0,
            highlightthickness=0,
            insertbackground="#6c5ce7"
        )
        self.conversation_display.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.conversation_display.tag_config("title", font=self.title_font, foreground="#6c5ce7")
        self.conversation_display.tag_config("subtitle", font=("Segoe UI", 12, "bold"), foreground="#2d3436")
        self.conversation_display.tag_config("content", font=self.content_font)
        self.conversation_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.conversation_display.tag_config("user", foreground="#00b894", font=("Segoe UI", 12, "bold"))
        
        input_frame = ttk.Frame(main_frame, style="Input.TFrame")
        input_frame.pack(fill=tk.X)
        
        self.user_input = ttk.Entry(
            input_frame,
            font=("Segoe UI", 12)
        )
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.handle_input)
        
        send_btn = ttk.Button(
            input_frame,
            text="Send",
            command=self.handle_input,
            style="Accent.TButton"
        )
        send_btn.pack(side=tk.RIGHT)
        
        self.user_input.focus()
        
        # Replay loaded conversation so user can see history
        for msg in self.conversation_history:
            sender = "You" if msg['role'] == 'user' else "Lingo"
            self.display_message(sender, msg['content'])
    
    def load_lesson(self):
        try:
            if not self.student_manager or not self.student_manager.current_user:
                raise ValueError("Student information not available")
            
            lesson = self.student_manager.lesson_manager.get_lesson_by_type(
                self.student_manager.current_user['level'],
                self.lesson_type,
                self.student_manager.current_user
            )
            
            if not lesson:
                messagebox.showerror("Error", "Lesson content not found")
                self.root.destroy()
                return
                
            self.current_lesson_path = lesson.get('filepath')
            self.student_manager.current_lesson = lesson
            
            self.display_lesson_content(lesson)
            self.display_personalized_welcome(lesson)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load lesson: {str(e)}")
            self.root.destroy()
    
    def display_lesson_content(self, lesson):
        self.display_message("system", "=== LESSON CONTENT ===", is_lesson=True)
        self.display_message("system", f"Lesson: {lesson.get('title', 'English Practice')}", is_lesson=True)
        
        if 'objective' in lesson:
            self.display_message("system", f"Objective: {lesson['objective']}", is_lesson=True)
        
        if 'text' in lesson:
            self.display_message("system", lesson['text'], is_lesson=True)
    
    def display_personalized_welcome(self, lesson):
        student_name = self.student_manager.current_user['name'].split()[0]
        praise = random.choice([
            "This is going to really boost your English skills!",
            "I'm excited to help you master this important area!",
            "You're making great progress by working on this!",
            "This lesson will take your English to the next level!"
        ])
        
        welcome_msg = (
            f"Hello {student_name}! I'm Lingo, Your Personal AI English Teacher.\n"
            f"Now it's time to learn {self.lesson_type.capitalize()}.\n"
            f"{praise}\n"
            f"Today we'll be working on: {lesson.get('title', 'English Practice')}\n"
        )
        
        if 'objective' in lesson:
            welcome_msg += f"\nOur goal is: {lesson['objective']}"
        
        self.display_message("Lingo", welcome_msg)
    
    def display_message(self, sender, message, is_lesson=False):
        self.conversation_display.configure(state='normal')
        
        if is_lesson:
            self.conversation_display.insert(tk.END, f"\n{message}\n", "content")
        else:
            self.conversation_display.insert(tk.END, f"\n{sender}: ", "ai" if sender == "Lingo" else "user")
            self.conversation_display.insert(tk.END, f"{message}\n", "message")
        
        self.conversation_display.see(tk.END)
        self.conversation_display.configure(state='disabled')
    
    def return_to_dashboard(self):
        try:
            # ✅ Save completion status
            if self.current_lesson_path and self.student_manager:
                self.student_manager.lesson_manager.record_lesson_completion(
                    self.student_manager.current_user['name'],
                    self.student_manager.current_lesson
                )

                data = load_json(self.STUDENTS_JSON_PATH)
                if "_default" in data and self.user_id in data["_default"]:
                    user_data = data["_default"][self.user_id]
                    completed = user_data.get("completed_lessons", [])
                    if self.current_lesson_path not in completed:
                        completed.append(self.current_lesson_path)
                        user_data["completed_lessons"] = completed
                        save_json(self.STUDENTS_JSON_PATH, data)

            # ✅ Release modal grab so Tk doesn't exit
            try:
                self.root.grab_release()
            except:
                pass

            # ✅ Destroy only the lesson Toplevel
            if isinstance(self.root, tk.Toplevel):
                self.root.destroy()

            # ✅ Refresh dashboard in the *existing* main root
            if hasattr(self.main_app, 'dashboard'):
                self.main_app.dashboard.update_display()
            elif hasattr(self.main_app, 'show_dashboard'):
                self.main_app.show_dashboard()

            # ✅ Bring main root to front
            if hasattr(self.main_app, 'root'):
                self.main_app.root.deiconify()
                self.main_app.root.lift()
                self.main_app.root.focus_force()

        except Exception as e:
            print(f"Error returning to dashboard: {e}")


    def handle_input(self, event=None):
        user_input = self.user_input.get().strip()
        if not user_input:
            return
            
        self.display_message("You", user_input)
        self.user_input.delete(0, tk.END)
        
        try:
            context = {
                'student': self.student_manager.current_user,
                'lesson': {
                    'title': self.current_lesson.get('title', ''),
                    'type': self.lesson_type,
                    'objective': self.current_lesson.get('objective', ''),
                    'content': self.current_lesson.get('text', '')
                }
            }
            system_prompt = self._generate_system_prompt(context)
            
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(self.student_manager.conversation_history)
            messages.append({"role": "user", "content": user_input})
            
            response = self.llm.get_ai_response(messages)
            
            self.display_message("Lingo", response)
            
            self.student_manager.conversation_history.extend([
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": response}
            ])
            
            # Save updated conversation
            self.conversation_data.setdefault(self.user_id, {})
            self.conversation_data[self.user_id][self.lesson_path] = self.student_manager.conversation_history
            save_json(self.CONVERSATIONS_JSON_PATH, self.conversation_data)
            
        except Exception as e:
            print(f"Error in lesson: {str(e)}")
            self.display_message("Lingo", "Let me check the material... One moment please!")
    
    def _generate_system_prompt(self, context):
        return (
            f"You are Lingo, a personal English tutor teaching {context['student']['name']} "
            f"(level: {context['student']['level']}).\n"
            f"Current lesson: {context['lesson']['title']} ({context['lesson']['type']})\n"
            f"Lesson objective: {context['lesson']['objective']}\n"
            f"Key content: {context['lesson']['content']}\n\n"
            "You must not use this symbol *"
            "Instructions:\n"
            "1. Respond with **only 2 vocabulary words or only 1 reading passage or only 1 grammar section or 3-4 sentences at a time.**\n"
            "2. End each response by asking a relevant question or requesting feedback.\n"
            "3. Be encouraging and supportive.\n"
            "4. Keep responses concise and interactive.\n"
            "5. Do NOT list long vocabulary or full lesson at once.\n"
            "6. Focus on the current lesson material.\n"
        )

    
    def _get_ai_response(self, system_prompt, user_input):
        """Handle AI response generation"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
        
        try:
            return self.main_app.llm.get_ai_response(
                messages=messages,
                conversation_history=self.student_manager.conversation_history
            )
        except Exception as e:
            print(f"AI response error: {e}")
            return "I'm having trouble processing that. Could you rephrase your question?"
    
    def _update_conversation_history(self, user_input, ai_response):
        """Update conversation history safely"""
        if self.student_manager:
            self.student_manager.conversation_history.extend([
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": ai_response}
            ])

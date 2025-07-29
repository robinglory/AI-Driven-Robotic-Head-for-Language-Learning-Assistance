import time
import os
import json
import random
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, PhotoImage
from PIL import Image, ImageTk
import threading
import requests
from io import BytesIO

# Load environment variables
load_dotenv()

# ======================
# MODEL & API MANAGEMENT
# ======================
class APIManager:
    def __init__(self):
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.minstral_api_key = os.getenv("MINSTRAL_API_KEY")
        self.current_model = "qwen/qwen3-coder:free"
        self.current_key = self.deepseek_api_key
        self.client = self._create_client()
        
    def _create_client(self):
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.current_key,
            timeout=10.0
        )
        client._client.headers = {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "Lingo Language Tutor"
        }
        return client
    
    def switch_to_backup(self):
        print("Lingo: Switching to backup API key (Mistral)...")
        self.current_key = self.minstral_api_key
        self.current_model = "mistralai/mistral-7b-instruct:free"
        self.client = self._create_client()

api_manager = APIManager()

# ======================
# STUDENT DATA MANAGEMENT
# ======================
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

student_manager = StudentManager()

# ======================
# LESSON MANAGEMENT
# ======================
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
            
            progress = student_manager.current_user['progress'].get(lesson_type.lower(), 0)
            lesson_index = min(int(progress * len(files)), len(files)-1)
            filepath = os.path.join(folder, files[lesson_index])
            
            with open(filepath, "r", encoding="utf-8") as f:
                lesson = json.load(f)
                lesson['filepath'] = filepath
                return lesson
            
        except Exception as e:
            print(f"Error loading lesson: {str(e)}")
            return None

    def understand_lesson_choice(self, input_text):
        input_text = input_text.lower()
        if any(word in input_text for word in ['read', '1']):
            return 'reading'
        elif any(word in input_text for word in ['grammar', '2', 'gram']):
            return 'grammar'
        elif any(word in input_text for word in ['vocab', '3', 'word']):
            return 'vocabulary'
        elif any(word in input_text for word in ['4', 'quit', 'exit', 'bye', 'stop', 'end']):
            return 'quit'
        return None

lesson_manager = LessonManager()

# ======================
# GUI APPLICATION
# ======================
class LingoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Lingo Language Tutor")
        self.root.geometry("900x700")
        self.root.configure(bg="#f0f2f5")
        
        # Load and resize logo
        try:
            response = requests.get("https://i.imgur.com/JQJZQyT.png")  # Placeholder logo URL
            img_data = response.content
            img = Image.open(BytesIO(img_data))
            img = img.resize((150, 150), Image.LANCZOS)
            self.logo = ImageTk.PhotoImage(img)
        except:
            # Fallback if no internet connection
            self.logo = None
        
        self.setup_ui()
        self.current_state = "login"
        
    def setup_ui(self):
        # Create main container
        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header with logo
        self.header_frame = ttk.Frame(self.main_frame)
        self.header_frame.pack(fill=tk.X, pady=(0, 20))
        
        if self.logo:
            logo_label = ttk.Label(self.header_frame, image=self.logo)
            logo_label.pack(side=tk.LEFT, padx=10)
        
        self.title_label = ttk.Label(
            self.header_frame,
            text="Lingo Language Tutor",
            font=("Helvetica", 20, "bold"),
            foreground="#2c3e50"
        )
        self.title_label.pack(side=tk.LEFT, padx=10)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(
            self.main_frame,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        self.update_status("Ready")
        
        # Create pages
        self.create_login_page()
        self.create_main_page()
        self.create_lesson_page()
        
        # Show login page initially
        self.show_page("login")
    
    def create_login_page(self):
        self.login_frame = ttk.Frame(self.main_frame)
        
        container = ttk.Frame(self.login_frame)
        container.pack(pady=50)
        
        ttk.Label(
            container,
            text="Welcome to Lingo!",
            font=("Helvetica", 16)
        ).pack(pady=10)
        
        ttk.Label(
            container,
            text="Please enter your full name:",
            font=("Helvetica", 12)
        ).pack(pady=5)
        
        self.name_entry = ttk.Entry(container, width=30, font=("Helvetica", 12))
        self.name_entry.pack(pady=10, ipady=5)
        
        self.login_button = ttk.Button(
            container,
            text="Start Learning",
            command=self.handle_login,
            style="Accent.TButton"
        )
        self.login_button.pack(pady=20, ipady=5, ipadx=20)
        
        self.login_error = ttk.Label(
            container,
            text="",
            foreground="red"
        )
        
    def create_main_page(self):
        self.main_page_frame = ttk.Frame(self.main_frame)
        
        container = ttk.Frame(self.main_page_frame)
        container.pack(pady=20, fill=tk.BOTH, expand=True)
        
        # Welcome message
        self.welcome_label = ttk.Label(
            container,
            text="",
            font=("Helvetica", 14),
            wraplength=600
        )
        self.welcome_label.pack(pady=20)
        
        # Lesson selection
        ttk.Label(
            container,
            text="What would you like to practice today?",
            font=("Helvetica", 12)
        ).pack(pady=10)
        
        button_frame = ttk.Frame(container)
        button_frame.pack(pady=20)
        
        style = ttk.Style()
        style.configure("Lesson.TButton", font=("Helvetica", 12), padding=10)
        
        self.reading_btn = ttk.Button(
            button_frame,
            text="📖 Reading",
            command=lambda: self.start_lesson("reading"),
            style="Lesson.TButton"
        )
        self.reading_btn.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        
        self.grammar_btn = ttk.Button(
            button_frame,
            text="📝 Grammar",
            command=lambda: self.start_lesson("grammar"),
            style="Lesson.TButton"
        )
        self.grammar_btn.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        
        self.vocab_btn = ttk.Button(
            button_frame,
            text="🔤 Vocabulary",
            command=lambda: self.start_lesson("vocabulary"),
            style="Lesson.TButton"
        )
        self.vocab_btn.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        self.quit_btn = ttk.Button(
            button_frame,
            text="🚪 Exit",
            command=self.quit_app,
            style="Lesson.TButton"
        )
        self.quit_btn.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        
        # Progress display
        self.progress_frame = ttk.LabelFrame(
            container,
            text="Your Progress",
            padding=10
        )
        self.progress_frame.pack(fill=tk.X, pady=20)
        
    def create_lesson_page(self):
        self.lesson_frame = ttk.Frame(self.main_frame)
        
        # Lesson content area
        self.lesson_content = scrolledtext.ScrolledText(
            self.lesson_frame,
            wrap=tk.WORD,
            font=("Helvetica", 12),
            height=15,
            padx=10,
            pady=10
        )
        self.lesson_content.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.lesson_content.configure(state='disabled')
        
        # User input area
        input_frame = ttk.Frame(self.lesson_frame)
        input_frame.pack(fill=tk.X, pady=10)
        
        self.user_input = ttk.Entry(
            input_frame,
            font=("Helvetica", 12)
        )
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.handle_lesson_input)
        
        self.send_btn = ttk.Button(
            input_frame,
            text="Send",
            command=self.handle_lesson_input,
            style="Accent.TButton"
        )
        self.send_btn.pack(side=tk.RIGHT)
        
        # Navigation buttons
        nav_frame = ttk.Frame(self.lesson_frame)
        nav_frame.pack(fill=tk.X)
        
        self.back_btn = ttk.Button(
            nav_frame,
            text="← Back to Menu",
            command=self.return_to_main
        )
        self.back_btn.pack(side=tk.LEFT)
        
    def show_page(self, page_name):
        for frame in [self.login_frame, self.main_page_frame, self.lesson_frame]:
            frame.pack_forget()
        
        if page_name == "login":
            self.login_frame.pack(fill=tk.BOTH, expand=True)
            self.name_entry.focus()
        elif page_name == "main":
            self.update_main_page()
            self.main_page_frame.pack(fill=tk.BOTH, expand=True)
        elif page_name == "lesson":
            self.lesson_frame.pack(fill=tk.BOTH, expand=True)
            self.user_input.focus()
    
    def update_status(self, message):
        self.status_var.set(f"Status: {message}")
    
    def handle_login(self):
        name = self.name_entry.get().strip().lower()
        if not name:
            self.login_error.config(text="Please enter your name")
            self.login_error.pack(pady=5)
            return
        
        student = student_manager.get_student(name)
        if not student:
            self.login_error.config(text="Name not recognized. Please try again.")
            self.login_error.pack(pady=5)
            return
        
        student_manager.current_user = student
        self.show_page("main")
    
    def update_main_page(self):
        if not student_manager.current_user:
            return
        
        # Update welcome message
        greeting = random.choice(LessonManager.GREETINGS).format(
            name=student_manager.current_user['name'].split()[0]
        )
        
        if student_manager.current_user['progress']:
            best_subject = max(
                student_manager.current_user['progress'].items(),
                key=lambda x: x[1]
            )[0]
            greeting += f" Last time we worked on {best_subject}."
        
        self.welcome_label.config(text=greeting)
        
        # Update progress display
        for widget in self.progress_frame.winfo_children():
            widget.destroy()
            
        for subject, progress in student_manager.current_user['progress'].items():
            progress_bar = ttk.Progressbar(
                self.progress_frame,
                orient=tk.HORIZONTAL,
                length=200,
                mode='determinate',
                value=progress*100
            )
            progress_bar.pack(fill=tk.X, pady=5)
            
            ttk.Label(
                self.progress_frame,
                text=f"{subject.capitalize()}: {int(progress*100)}%",
                font=("Helvetica", 10)
            ).pack(anchor=tk.W)
    
    def start_lesson(self, lesson_type):
        lesson = lesson_manager.get_lesson_by_type(
            student_manager.current_user['level'],
            lesson_type.capitalize()
        )
        
        if not lesson:
            messagebox.showerror("Error", "Couldn't find a lesson for that topic.")
            return
        
        student_manager.current_lesson = lesson
        student_manager.current_topic = lesson_type
        
        # Display lesson content
        self.lesson_content.configure(state='normal')
        self.lesson_content.delete(1.0, tk.END)
        
        title = lesson.get('title', 'English Practice')
        self.lesson_content.insert(tk.END, f"Lesson: {title}\n\n", "title")
        
        if 'objective' in lesson:
            self.lesson_content.insert(tk.END, f"Objective: {lesson['objective']}\n\n", "subtitle")
        
        if 'text' in lesson:
            self.lesson_content.insert(tk.END, f"{lesson['text']}\n\n", "content")
        
        self.lesson_content.tag_config("title", font=("Helvetica", 14, "bold"))
        self.lesson_content.tag_config("subtitle", font=("Helvetica", 12, "bold"))
        self.lesson_content.tag_config("content", font=("Helvetica", 12))
        
        self.lesson_content.configure(state='disabled')
        self.show_page("lesson")
        
        # Start with an AI greeting
        encouragement = random.choice(LessonManager.ENCOURAGEMENTS)
        self.display_ai_message(f"{encouragement} Today's lesson: {title}")
    
    def handle_lesson_input(self, event=None):
        user_input = self.user_input.get().strip()
        if not user_input:
            return
        
        # Add user message to conversation
        self.display_user_message(user_input)
        self.user_input.delete(0, tk.END)
        
        # Handle special commands
        if user_input.lower() in ['back', 'menu']:
            self.return_to_main()
            return
        
        # Get AI response in a separate thread
        threading.Thread(
            target=self.get_ai_response,
            args=(user_input,),
            daemon=True
        ).start()
    
    def get_ai_response(self, user_input):
        self.update_status("Lingo is thinking...")
        self.root.config(cursor="watch")
        
        try:
            response = self.ask_lingo(user_input)
            self.display_ai_message(response)
            
            if user_input.lower() in ["quit", "exit", "bye", "that's all for today"]:
                self.return_to_main()
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")
        finally:
            self.root.config(cursor="")
            self.update_status("Ready")
    
    def ask_lingo(self, question):
        if question.lower() in ["quit", "exit", "bye", "that's all for today"]:
            if student_manager.current_topic:
                student_manager.update_progress(student_manager.current_topic)
            return random.choice([
                "It was a pleasure teaching you today!",
                "Great work today! I'm proud of your progress.",
                "Wonderful session! Let's continue next time.",
                "You're doing amazing! Until next time."
            ])

        # Prepare context for the AI
        context = []
        
        if student_manager.current_lesson:
            context.append(f"Current Lesson: {student_manager.current_lesson.get('title', '')}")
            if 'objective' in student_manager.current_lesson:
                context.append(f"Lesson Objective: {student_manager.current_lesson['objective']}")
            if 'text' in student_manager.current_lesson:
                context.append(f"Key Content: {student_manager.current_lesson['text'][:200]}...")
        
        context.append(f"Student Level: {student_manager.current_user['level']}")
        context.append(f"Student Name: {student_manager.current_user['name']}")
        
        if student_manager.current_user['progress']:
            progress_str = ", ".join([f"{k}: {int(v*100)}%" for k,v in student_manager.current_user['progress'].items()])
            context.append(f"Student Progress: {progress_str}")
        
        context.append(f"Student Question: {question}")
        
        # Build conversation history
        messages = [
            {"role": "system", "content": "You are Lingo, a friendly, patient English teaching AI. "
             "You teach English to non-native speakers. Be warm, encouraging, and engaging. "
             "Adapt to the student's level. Ask questions to check understanding. "
             "Use the lesson content but don't just recite it - explain clearly. "
             "Keep responses under 4 sentences unless explaining complex concepts."}
        ]
        
        messages.extend(student_manager.conversation_history[-4:])
        messages.append({"role": "user", "content": "\n".join(context)})
        
        try:
            try:
                response = api_manager.client.chat.completions.create(
                    model=api_manager.current_model,
                    messages=messages,
                    max_tokens=150,
                    temperature=0.8,
                )
                reply = response.choices[0].message.content.strip()
                student_manager.conversation_history.append({"role": "assistant", "content": reply})
                return reply

            except Exception as e:
                if "invalid_api_key" in str(e).lower() or "unauthorized" in str(e).lower():
                    api_manager.switch_to_backup()
                    return self.ask_lingo(question)  # retry with backup

                return f"I'm having trouble thinking right now. Could you try asking again? ({str(e)})"
            
        except Exception as e:
            return f"I'm having trouble thinking right now. Could you try asking again? ({str(e)})"
    
    def display_user_message(self, message):
        self.lesson_content.configure(state='normal')
        self.lesson_content.insert(tk.END, f"\nYou: {message}\n", "user")
        self.lesson_content.tag_config("user", foreground="blue", font=("Helvetica", 12, "bold"))
        self.lesson_content.see(tk.END)
        self.lesson_content.configure(state='disabled')
    
    def display_ai_message(self, message):
        self.lesson_content.configure(state='normal')
        self.lesson_content.insert(tk.END, f"\nLingo: {message}\n", "ai")
        self.lesson_content.tag_config("ai", foreground="green", font=("Helvetica", 12))
        self.lesson_content.see(tk.END)
        self.lesson_content.configure(state='disabled')
    
    def return_to_main(self):
        if student_manager.current_topic:
            student_manager.update_progress(student_manager.current_topic)
        self.show_page("main")
    
    def quit_app(self):
        if messagebox.askokcancel("Quit", "Are you sure you want to quit?"):
            self.root.destroy()

# ======================
# RUN THE APPLICATION
# ======================
if __name__ == "__main__":
    root = tk.Tk()
    
    # Configure styles
    style = ttk.Style()
    style.theme_use("clam")
    
    # Custom styles
    style.configure("TFrame", background="#f0f2f5")
    style.configure("TLabel", background="#f0f2f5", font=("Helvetica", 12))
    style.configure("TButton", font=("Helvetica", 12), padding=6)
    style.configure("Accent.TButton", font=("Helvetica", 12, "bold"), foreground="white", background="#3498db")
    style.map("Accent.TButton",
              foreground=[('pressed', 'white'), ('active', 'white')],
              background=[('pressed', '#2980b9'), ('active', '#2980b9')])
    
    app = LingoApp(root)
    root.mainloop()
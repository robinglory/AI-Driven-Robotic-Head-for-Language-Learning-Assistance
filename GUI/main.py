import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import random
from datetime import datetime
from openai import OpenAI
import os
from dotenv import load_dotenv
import sys
import os
import threading

# Add these imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from GUI.styles import configure_styles
from GUI.login import LoginScreen
from GUI.student_manager import StudentManager  # Add this import
from GUI.lesson_manager import LessonManager  # Add this import

# Load environment variables
load_dotenv()

class LLMHandler:
    def __init__(self):
        self.api_providers = [
            {
                "name": "Qwen3 Coder",
                "api_key": os.getenv("QWEN_API_KEY"),
                "model": "qwen/qwen3-coder:free",
                "headers": {
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Lingo AI Assistant"
                }
            },
            {
                "name": "Mistral 7B",
                "api_key": os.getenv("MISTRAL_API_KEY"),
                "model": "mistralai/mistral-7b-instruct:free",
                "headers": {
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Lingo AI Assistant"
                }
            },
            {
                "name": "GPT-OSS-20B",
                "api_key": os.getenv("GPT_OSS_API_KEY"),
                "model": "openai/gpt-oss-20b:free",
                "headers": {
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Lingo AI Assistant"
                }
            }
        ]
        self.current_provider = 0  # Start with Qwen
        self.client = self._create_client()
    
    def _create_client(self):
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_providers[self.current_provider]["api_key"],
            timeout=20.0  # Increased timeout for free models
        )
    
    def _switch_provider(self):
        self.current_provider = (self.current_provider + 1) % len(self.api_providers)
        print(f"Switching to {self.api_providers[self.current_provider]['name']}...")
        self.client = self._create_client()
    
    def get_ai_response(self, message=None, conversation_history=None, lesson_context=None, messages=None):
        """Handle both calling conventions:
        - General mode: get_ai_response(message, conversation_history)
        - Lesson mode: get_ai_response(message, conversation_history, lesson_context)
        """
        # Convert to messages format if needed
        if messages is None:
            if message is None:
                raise ValueError("Either message or messages must be provided")
            
            # Create system message based on context
            if lesson_context:
                system_msg = (
                    f"You are Lingo teaching {lesson_context['student_name']} (Level: {lesson_context['student_level']}). "
                    f"Current Lesson: {lesson_context['lesson_title']}\n"
                    f"Objective: {lesson_context['lesson_objective']}\n"
                    "Guidelines:\n"
                    "1. Reference the lesson content\n"
                    "2. Personalize explanations\n"
                    "3. Keep responses focused"
                )
            else:
                system_msg = (
                    "You are Lingo, a friendly AI English Teacher. "
                    "Have natural conversations and help with general English questions. "
                    "Keep responses under 3 sentences."
                    "You must not use this * symbol at all."
                )
            
            messages = [
                {"role": "system", "content": system_msg}
            ]
            if conversation_history:
                messages.extend(conversation_history[-4:])
            messages.append({"role": "user", "content": message})

        retry_count = 0
        max_retries = len(self.api_providers)
        
        while retry_count < max_retries:
            try:
                provider = self.api_providers[self.current_provider]
                self.client._client.headers.update(provider["headers"])
                
                response = self.client.chat.completions.create(
                    model=provider["model"],
                    messages=messages,
                    max_tokens=175,
                    temperature=0.7
                )
                return response.choices[0].message.content.strip()
                
            except Exception as e:
                print(f"Error with {provider['name']}: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    self._switch_provider()
                else:
                    return "I'm having trouble connecting. Please try again."
                
class MainAIChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Lingo - AI English Teacher")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg="#f8f9fa")
        
        # Configure styles
        configure_styles()
        
        # Initialize services in correct order
        self.llm = LLMHandler()
        self.lesson_manager = LessonManager(llm_handler=self.llm)
        self.student_manager = StudentManager(lesson_manager=self.lesson_manager)
        
        # Add this to track current lesson
        self.current_lesson = None
        self.conversation_history = []
        self.login_window = None
        self.dashboard_window = None
        
        self.create_widgets()
        
    def show_dashboard(self):
        if self.dashboard_window and self.dashboard_window.winfo_exists():
            self.dashboard_window.lift()
            return
        self.root.withdraw()  # Hide main window

        dashboard_root = tk.Toplevel(self.root)
        self.dashboard_window = dashboard_root

        from GUI.dashboard import Dashboard  # adjust import path as needed
        dashboard = Dashboard(dashboard_root, self, self.student_manager)

        dashboard_root.geometry("1000x700")
        dashboard_root.protocol("WM_DELETE_WINDOW", self.return_to_main)
        dashboard_root.transient(self.root)
        dashboard_root.grab_set()
        
    def create_widgets(self):
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding=(20, 15))
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header with modern styling
        header_frame = ttk.Frame(main_frame, style="Header.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 20), ipady=10)
        
        ttk.Label(
            header_frame,
            text="Lingo - AI English Teacher",
            style="Header.TLabel"
        ).pack(side=tk.LEFT, padx=10)
        
        # Login button with modern style
        login_btn = ttk.Button(
            header_frame,
            text="Login to Personal Tutor Mode",
            command=self.open_login,
            style="Accent.TButton"
        )
        login_btn.pack(side=tk.RIGHT, padx=10)
        
        # Chat display area with modern styling
        chat_frame = ttk.Frame(main_frame, style="Chat.TFrame")
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 12),
            height=20,
            padx=15,
            pady=15,
            state='disabled',
            bg="white",
            fg="#2d3436",
            bd=0,
            highlightthickness=0,
            insertbackground="#6c5ce7"
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # Input area with modern styling
        input_frame = ttk.Frame(main_frame, style="Input.TFrame")
        input_frame.pack(fill=tk.X)
        
        self.user_input = ttk.Entry(
            input_frame,
            font=("Segoe UI", 12)
        )
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.send_message)
        
        send_btn = ttk.Button(
            input_frame,
            text="Send",
            command=self.send_message,
            style="Accent.TButton"
        )
        send_btn.pack(side=tk.RIGHT)
        
        # Welcome message
        self.display_message("Lingo", "Hello! I'm Lingo, your AI English Teacher. How can I help you today?")
        
    def display_message(self, sender, message):
        self.chat_display.configure(state='normal')
        
        # Configure tags for different senders
        self.chat_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("user", foreground="#00b894", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)
        
        # Insert sender name
        self.chat_display.insert(tk.END, f"{sender}: ", "ai" if sender == "Lingo" else "user")
        
        # Insert message with proper formatting
        self.chat_display.insert(tk.END, f"{message}\n\n", "message")
        
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')
    
    def send_message(self, event=None):
        message = self.user_input.get().strip()
        if not message:
            return
            
        self.display_message("You", message)
        self.user_input.delete(0, tk.END)
        
        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": message})
        
        # Check for simple commands first
        simple_response = self.get_simple_response(message.lower())
        if simple_response:
            self.display_message("Lingo", simple_response)
            self.conversation_history.append({"role": "assistant", "content": simple_response})
            return
            
        # Get LLM response
        self.root.config(cursor="watch")
        self.root.update()
        
        try:
            # Check if we're in authenticated lesson mode
            if hasattr(self.student_manager, 'current_user') and self.student_manager.current_user:
                # Get current lesson context if available
                lesson_context = None
                if hasattr(self, 'current_lesson') and self.current_lesson:
                    lesson_context = {
                        'student_name': self.student_manager.current_user['name'],
                        'student_level': self.student_manager.current_user['level'],
                        'lesson_title': self.current_lesson.get('title', ''),
                        'lesson_objective': self.current_lesson.get('objective', '')
                    }
                
                response = self.llm.get_ai_response(
                    message=message,
                    conversation_history=self.conversation_history,
                    lesson_context=lesson_context
                )
            else:
                # General chat mode
                response = self.llm.get_ai_response(
                    message=message,
                    conversation_history=self.conversation_history
                )
                
            self.display_message("Lingo", response)
            self.conversation_history.append({"role": "assistant", "content": response})
        except Exception as e:
            self.display_message("Lingo", f"Sorry, I encountered an error: {str(e)}")
        finally:
            self.root.config(cursor="")
    
    def get_simple_response(self, message):
        """Handle simple commands without LLM"""
        if any(word in message for word in ["hello", "hi", "hey"]):
            return random.choice([
                "Hello there! How can I help you today?",
                "Hi! What would you like to know?",
                "Greetings! What's on your mind?"
            ])
        elif any(word in message for word in ["how are you", "how's it going"]):
            return "I'm just a computer program, but I'm functioning well! How about you?"
        elif any(word in message for word in ["bye", "goodbye", "see you"]):
            return "Goodbye! Feel free to come back if you have more questions."
        elif "time" in message:
            return f"The current time is {datetime.now().strftime('%H:%M')}."
        elif "date" in message:
            return f"Today's date is {datetime.now().strftime('%Y-%m-%d')}."
        return None
    
    def open_login(self):
        if self.login_window and self.login_window.winfo_exists():
            self.login_window.lift()
            return
            
        # Create login window as Toplevel of main window
        self.login_window = tk.Toplevel(self.root)
        self.login_window.protocol("WM_DELETE_WINDOW", lambda: self.on_login_close())
        LoginScreen(self.login_window, self)
        
        # Center the login window
        self.login_window.geometry("400x300")
        self.login_window.transient(self.root)
        self.login_window.grab_set()
    
    def on_login_close(self):
        """Handle when login window is closed"""
        if self.login_window:
            self.login_window.destroy()
            self.login_window = None
    
    def return_to_main(self):
        """Called when returning from dashboard"""
        if self.dashboard_window:
            self.dashboard_window.destroy()
            self.dashboard_window = None
        self.root.deiconify()

if __name__ == "__main__":
    root = tk.Tk()
    app = MainAIChat(root)
    root.mainloop()

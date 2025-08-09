import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import random
from datetime import datetime
from openai import OpenAI
import os
from dotenv import load_dotenv
import sys
import os
import threading  # Add this import at the top

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from GUI.styles import configure_styles
from GUI.login import LoginScreen  # Make sure this import is correct
# Load environment variables
load_dotenv()

class LLMHandler:
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
            "X-Title": "Lingo AI Assistant"
        }
        return client
    
    def switch_to_backup(self):
        print("Lingo: Switching to backup API key (Mistral)...")
        self.current_key = self.minstral_api_key
        self.current_model = "mistralai/mistral-7b-instruct:free"
        self.client = self._create_client()
    
    def get_ai_response(self, message, conversation_history):
        try:
            messages = [
                {"role": "system", "content": "You are Lingo, a friendly AI English Teacher. "
                 "Be helpful, concise and engaging in your responses. "
                 "Keep responses under 3 sentences unless explaining complex english concepts."}
            ]
            
            messages.extend(conversation_history[-4:])
            messages.append({"role": "user", "content": message})
            
            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                max_tokens=150,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            if "invalid_api_key" in str(e).lower() or "unauthorized" in str(e).lower():
                self.switch_to_backup()
                return self.get_ai_response(message, conversation_history)
            return f"I'm having trouble thinking right now. Could you try again? ({str(e)})"

class MainAIChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Lingo - AI English Teacher")
        self.root.geometry("800x600")
        configure_styles()
        
        self.llm = LLMHandler()
        self.conversation_history = []
        
        self.login_window = None  # Track login window
        self.dashboard_window = None
        self.create_widgets()
        
    def create_widgets(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(
            header_frame,
            text="Lingo AI English Teacher",
            font=("Helvetica", 18, "bold"),
            foreground="#2c3e50"
        ).pack(side=tk.LEFT)
        
        # Login button
        login_btn = ttk.Button(
            header_frame,
            text="Login to Tutor Mode",
            command=self.open_login,
            style="Accent.TButton"
        )
        login_btn.pack(side=tk.RIGHT)
        
        # Chat area
        self.chat_display = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            font=("Helvetica", 12),
            height=20,
            padx=10,
            pady=10,
            state='disabled'
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Input area
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X)
        
        self.user_input = ttk.Entry(
            input_frame,
            font=("Helvetica", 12)
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
        self.display_message("Lingo", "Hello! I'm Lingo, an AI English Teacher. How can I help you today?")
        
    def display_message(self, sender, message):
        self.chat_display.configure(state='normal')
        self.chat_display.insert(tk.END, f"\n{sender}: {message}\n")
        
        # Apply tags based on sender
        if sender == "Lingo":
            self.chat_display.tag_config("ai", foreground="green")
            self.chat_display.tag_add("ai", "end-2l linestart", "end-1c")
        else:
            self.chat_display.tag_config("user", foreground="blue")
            self.chat_display.tag_add("user", "end-2l linestart", "end-1c")
            
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
            response = self.llm.get_ai_response(message, self.conversation_history)
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
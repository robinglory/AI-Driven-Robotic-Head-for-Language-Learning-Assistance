import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from styles import configure_styles

class LessonScreen:
    def __init__(self, root, main_app, student_manager, lesson_type):
        self.root = root
        self.main_app = main_app
        self.student_manager = student_manager
        self.lesson_type = lesson_type
        
        self.root.title(f"Lingo - {lesson_type.capitalize()} Lesson")
        configure_styles()
        
        self.create_widgets()
        self.load_lesson()
        
    def create_widgets(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(
            header_frame,
            text=f"{self.lesson_type.capitalize()} Lesson",
            font=("Helvetica", 16, "bold"),
            foreground="#2c3e50"
        ).pack(side=tk.LEFT)
        
        # Back button
        back_btn = ttk.Button(
            header_frame,
            text="← Back to Dashboard",
            command=self.return_to_dashboard
        )
        back_btn.pack(side=tk.RIGHT)
        
        # Lesson content area
        self.lesson_content = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            font=("Helvetica", 12),
            height=20,
            padx=10,
            pady=10,
            state='disabled'
        )
        self.lesson_content.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Input area
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=10)
        
        self.user_input = ttk.Entry(
            input_frame,
            font=("Helvetica", 12)
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
        
        # Focus on input field
        self.user_input.focus()
    
    def load_lesson(self):
        lesson = self.student_manager.get_lesson_by_type(
            self.student_manager.current_user['level'],
            self.lesson_type.capitalize()
        )
        
        if not lesson:
            messagebox.showerror("Error", "Couldn't load the lesson.")
            self.root.destroy()
            return
            
        self.student_manager.current_lesson = lesson
        
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
        
        # Display welcome message
        self.display_message("Lingo", f"Let's begin our {self.lesson_type} lesson!")
    
    def display_message(self, sender, message):
        self.lesson_content.configure(state='normal')
        self.lesson_content.insert(tk.END, f"\n{sender}: {message}\n")
        
        if sender == "Lingo":
            self.lesson_content.tag_config("ai", foreground="green")
            self.lesson_content.tag_add("ai", "end-2l linestart", "end-1c")
        else:
            self.lesson_content.tag_config("user", foreground="blue")
            self.lesson_content.tag_add("user", "end-2l linestart", "end-1c")
                    
        self.lesson_content.see(tk.END)
        self.lesson_content.configure(state='disabled')
    
    def handle_input(self, event=None):
        user_input = self.user_input.get().strip()
        if not user_input:
            return
            
        self.display_message("You", user_input)
        self.user_input.delete(0, tk.END)
        
        # Handle special commands
        if user_input.lower() in ['back', 'menu']:
            self.return_to_dashboard()
            return
            
        # Get AI response through student_manager
        response = self.student_manager.lesson_manager.ask_lingo(
            user_input,
            self.student_manager.current_user,
            self.student_manager.current_lesson,
            self.student_manager.conversation_history
        )
        
        self.display_message("Lingo", response)
        
        # Update progress if ending lesson
        if user_input.lower() in ["quit", "exit", "bye", "that's all for today"]:
            self.student_manager.update_progress(self.lesson_type)
            self.return_to_dashboard()
    
    def return_to_dashboard(self):
        self.root.destroy()
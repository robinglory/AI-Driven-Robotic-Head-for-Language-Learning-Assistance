import tkinter as tk
from tkinter import ttk
from styles import configure_styles
import lesson

class Dashboard:
    def __init__(self, root, main_app, student_manager):
        self.root = root
        self.main_app = main_app
        self.student_manager = student_manager
        
        self.root.title(f"Lingo - {student_manager.current_user['name']}")
        configure_styles()
        
        self.create_widgets()
        self.update_display()
        
    def create_widgets(self):
        # Main container
        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(self.main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(
            header_frame,
            text=f"Welcome, {self.student_manager.current_user['name']}!",
            font=("Helvetica", 16, "bold"),
            foreground="#2c3e50"
        ).pack(side=tk.LEFT)
        
        # Logout button
        logout_btn = ttk.Button(
            header_frame,
            text="Logout",
            command=self.logout,
            style="Accent.TButton"
        )
        logout_btn.pack(side=tk.RIGHT)
        
        # Welcome message
        self.welcome_label = ttk.Label(
            self.main_frame,
            text="",
            font=("Helvetica", 12),
            wraplength=600
        )
        self.welcome_label.pack(pady=20)
        
        # Lesson selection
        ttk.Label(
            self.main_frame,
            text="What would you like to practice today?",
            font=("Helvetica", 12)
        ).pack(pady=10)
        
        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(pady=20)
        
        # Lesson buttons
        ttk.Button(
            button_frame,
            text="📖 Reading",
            command=lambda: self.start_lesson("reading"),
            style="Lesson.TButton"
        ).grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        
        ttk.Button(
            button_frame,
            text="📝 Grammar",
            command=lambda: self.start_lesson("grammar"),
            style="Lesson.TButton"
        ).grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        
        ttk.Button(
            button_frame,
            text="🔤 Vocabulary",
            command=lambda: self.start_lesson("vocabulary"),
            style="Lesson.TButton"
        ).grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        ttk.Button(
            button_frame,
            text="🔙 Back to AI Chat",
            command=self.return_to_main,
            style="Lesson.TButton"
        ).grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        
        # Progress display
        self.progress_frame = ttk.LabelFrame(
            self.main_frame,
            text="Your Progress",
            padding=10
        )
        self.progress_frame.pack(fill=tk.X, pady=20)
        
    def update_display(self):
        # Update welcome message
        greeting = f"Welcome back, {self.student_manager.current_user['name'].split()[0]}!"
        
        if self.student_manager.current_user['progress']:
            best_subject = max(
                self.student_manager.current_user['progress'].items(),
                key=lambda x: x[1]
            )[0]
            greeting += f" Your best subject is {best_subject}."
        
        self.welcome_label.config(text=greeting)
        
        # Update progress display
        for widget in self.progress_frame.winfo_children():
            widget.destroy()
            
        for subject, progress in self.student_manager.current_user['progress'].items():
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
        # Open lesson window
        lesson_window = tk.Toplevel()
        lesson.LessonScreen(
            lesson_window,
            self.main_app,
            self.student_manager,
            lesson_type
        )
        
        # Center the lesson window
        lesson_window.geometry("900x700")
        lesson_window.transient(self.root)
        lesson_window.grab_set()
    
    def logout(self):
        # Confirm logout
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.student_manager.current_user = None
            self.root.destroy()
            
            # Reopen login screen
            login_window = tk.Toplevel()
            login.LoginScreen(login_window, self.main_app)
            
            # Center the login window
            login_window.geometry("400x300")
            login_window.transient(self.main_app.root)
            login_window.grab_set()
    
    def return_to_main(self):
        self.root.destroy()
        self.main_app.root.deiconify()
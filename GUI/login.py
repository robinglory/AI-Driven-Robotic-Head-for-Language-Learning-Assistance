# login.py
import tkinter as tk
from tkinter import ttk, messagebox
from styles import configure_styles
import dashboard
from student_manager import StudentManager

class LoginScreen:
    def __init__(self, root, main_app):
        self.root = root
        self.main_app = main_app
        self.student_manager = StudentManager()
        
        self.root.title("Lingo - Login")
        configure_styles()
        
        self.create_widgets()
        
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(
            main_frame,
            text="Welcome to Lingo Tutor",
            font=("Helvetica", 16, "bold")
        ).pack(pady=(0, 20))
        
        ttk.Label(
            main_frame,
            text="Please enter your full name:",
            font=("Helvetica", 12)
        ).pack(pady=5)
        
        self.name_entry = ttk.Entry(
            main_frame,
            font=("Helvetica", 12),
            width=25
        )
        self.name_entry.pack(pady=10, ipady=5)
        self.name_entry.focus()
        
        login_btn = ttk.Button(
            main_frame,
            text="Login",
            command=self.handle_login,
            style="Accent.TButton"
        )
        login_btn.pack(pady=20, ipady=5, ipadx=20)
        
        self.error_label = ttk.Label(
            main_frame,
            text="",
            foreground="red"
        )
        self.error_label.pack()
        
        # Bind Enter key to login
        self.name_entry.bind("<Return>", lambda e: self.handle_login())
        
    def handle_login(self):
        name = self.name_entry.get().strip()
        if not name:
            self.error_label.config(text="Please enter your name")
            return
            
        student = self.student_manager.get_student(name)
        if not student:
            self.error_label.config(text="Name not recognized. Please try again.")
            return
            
        # Successful login
        self.student_manager.current_user = student
        
        # Close login window properly
        self.root.destroy()
        
        # Open dashboard - pass the main app's root window
        dashboard_window = tk.Toplevel(self.main_app.root)
        dashboard.Dashboard(dashboard_window, self.main_app, self.student_manager)
        
        # Center the dashboard window
        dashboard_window.geometry("900x700")
        dashboard_window.transient(self.main_app.root)
        dashboard_window.grab_set()
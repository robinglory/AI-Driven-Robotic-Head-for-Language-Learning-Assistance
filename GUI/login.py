import tkinter as tk
from tkinter import ttk, messagebox
from styles import configure_styles
import dashboard
from student_manager import StudentManager
from datetime import datetime  # Add this import

class LoginScreen:
    def __init__(self, root, main_app):
        self.root = root
        self.main_app = main_app
        self.student_manager = main_app.student_manager
        
        self.root.title("Lingo - Login")
        self.root.geometry("400x450")  # Smaller window size
        self.root.resizable(False, False)
        configure_styles()
        
        # Configure custom button styles
        self._configure_styles()
        
        try:
            self.root.iconbitmap('assets/logo.ico')
        except:
            pass
            
        self.create_widgets()
        
    def _configure_styles(self):
        style = ttk.Style()
        
        # Green continue button
        style.configure("Green.TButton",
                      foreground="white",
                      background="#2ecc71",
                      font=("Segoe UI", 10, "bold"),
                      padding=8)
        style.map("Green.TButton",
                background=[("active", "#27ae60")])
        
        # Purple register button
        style.configure("Purple.TButton",
                      foreground="white",
                      background="#6c5ce7",
                      font=("Segoe UI", 10),
                      padding=8)
        style.map("Purple.TButton",
                background=[("active", "#5c63e7")])
        
    def create_widgets(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # ✅ Add this immediately after main_frame is packed
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.resizable(True, True)
                
        # Logo section
        logo_frame = ttk.Frame(main_frame)
        logo_frame.pack(pady=10)
        
        ttk.Label(
            logo_frame,
            text="LINGO",
            font=("Segoe UI", 22, "bold"),
            foreground="#6c5ce7"
        ).pack()
        
        ttk.Label(
            logo_frame,
            text="AI Language Tutor",
            font=("Segoe UI", 10),
            foreground="#636e72"
        ).pack()
        
        # Login form
        form_frame = ttk.Frame(main_frame)
        form_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(
            form_frame,
            text="Enter Your Full Name:",
            font=("Segoe UI", 10)
        ).pack(anchor=tk.W, pady=(10, 5))
        
        self.name_entry = ttk.Entry(
            form_frame,
            font=("Segoe UI", 11)
        )
        self.name_entry.pack(fill=tk.X, pady=5, ipady=5)
        self.name_entry.focus()
        
        # Level selection
        ttk.Label(
            form_frame,
            text="Select Your English Level:",
            font=("Segoe UI", 10)
        ).pack(anchor=tk.W, pady=(10, 5))
        
        self.level_var = tk.StringVar(value="A2")
        level_frame = ttk.Frame(form_frame)
        level_frame.pack(fill=tk.X, pady=5)
        
        ttk.Radiobutton(
            level_frame,
            text="Pre-Intermediate (A2)",
            variable=self.level_var,
            value="A2"
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Radiobutton(
            level_frame,
            text="Intermediate (B1)",
            variable=self.level_var,
            value="B1"
        ).pack(side=tk.LEFT)
        
        # Button frame
        button_frame = ttk.Frame(form_frame)
        button_frame.pack(fill=tk.X, pady=(15, 5))

        # Make button frame responsive with grid
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        # Green continue button
        ttk.Button(
            button_frame,
            text="CONTINUE",
            command=self.handle_login,
            style="Green.TButton"
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))

        # Purple register button
        ttk.Button(
            button_frame,
            text="NEW STUDENT",
            command=self.handle_registration,
            style="Purple.TButton"
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        
        # Error message label
        self.error_label = ttk.Label(
            form_frame,
            text="",
            foreground="#e74c3c",
            font=("Segoe UI", 9)
        )
        self.error_label.pack(pady=(5, 0))
        
        self.name_entry.bind("<Return>", lambda e: self.handle_login())
        
    def handle_login(self):
        name = self.name_entry.get().strip()
        if not name:
            self.error_label.config(text="Please enter your full name")
            return
            
        student = self.student_manager.get_student(name)
        if not student:
            self.error_label.config(text="Name not recognized. Please register.")
            return
            
        self.student_manager.current_user = student
        self.root.destroy()
        self.open_dashboard()
        
    def handle_registration(self):
        name = self.name_entry.get().strip()
        if not name:
            self.error_label.config(text="Please enter your full name")
            return
            
        # Check if student exists
        if self.student_manager.get_student(name):
            self.error_label.config(text="Student already exists. Please login.")
            return
            
        # Create new student
        new_student = {
            "name": name,
            "level": self.level_var.get(),
            "progress": {
                "reading": 0.0,
                "grammar": 0.0,
                "vocabulary": 0.0
            },
            "completed_lessons": [],
            "created_at": datetime.now().isoformat()  # Now properly imported
        }
        
        # Add to database
        self.student_manager.db.insert(new_student)
        self.student_manager.current_user = new_student
        
        messagebox.showinfo("Welcome", f"Welcome {name}!\nYour account has been created.")
        self.root.destroy()
        self.open_dashboard()
        
    def open_dashboard(self):
        dashboard_window = tk.Toplevel(self.main_app.root)
        dashboard.Dashboard(dashboard_window, self.main_app, self.student_manager)
        dashboard_window.geometry("1000x800")
        dashboard_window.transient(self.main_app.root)
        dashboard_window.grab_set()
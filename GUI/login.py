#!/usr/bin/env python3
import os, sys, json, subprocess, threading
import tkinter as tk
from tkinter import ttk, messagebox
from styles import configure_styles
import dashboard
from student_manager import StudentManager
from datetime import datetime

class LoginScreen:
    def __init__(self, root, main_app):
        self.root = root
        self.main_app = main_app
        self.student_manager = main_app.student_manager

        self.root.title("Lingo - Login")
        self.root.geometry("560x520")
        self.root.resizable(False, False)
        configure_styles()
        self._configure_styles()

        try:
            self.root.iconbitmap('assets/logo.ico')
        except:
            pass

        self._resolve_paths()
        self.create_widgets()

    def _resolve_paths(self):
        here = os.path.abspath(os.path.dirname(__file__))
        self.face_dir = os.path.join(here, "Face_Recognition")
        self.recognize_py = os.path.join(self.face_dir, "recognize_live.py")
        self.gui_face_rec_py = os.path.join(self.face_dir, "gui_face_rec.py")
        self.py_exec = sys.executable

    def _configure_styles(self):
        style = ttk.Style()
        # Keep your existing styles
        style.configure("Green.TButton", foreground="white", background="#2ecc71",
                        font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Green.TButton", background=[("active", "#27ae60")])
        style.configure("Purple.TButton", foreground="white", background="#6c5ce7",
                        font=("Segoe UI", 10), padding=8)
        style.map("Purple.TButton", background=[("active", "#5c63e7")])
        # Extra styles to match the rest of your app
        style.configure("Title.TLabel", foreground="#6c5ce7", font=("Segoe UI", 22, "bold"))
        style.configure("Sub.TLabel", foreground="#636e72", font=("Segoe UI", 10))
        style.configure("Info.TLabel", foreground="#2d3436", font=("Segoe UI", 10))

    def create_widgets(self):
        # Container
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.resizable(True, True)

        # Branding
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text="LINGO", style="Title.TLabel").pack(anchor="center")
        ttk.Label(header, text="AI Language Tutor", style="Sub.TLabel").pack(anchor="center")

        # Tabs
        nb = ttk.Notebook(main)
        nb.pack(fill=tk.BOTH, expand=True, pady=(12,0))

        # --- TAB A: Log-in (default) ---
        self.tab_login = ttk.Frame(nb, padding=16)
        nb.add(self.tab_login, text="Log in")
        self._build_tab_login(self.tab_login)

        # --- TAB B: Sign-up ---
        self.tab_signup = ttk.Frame(nb, padding=16)
        nb.add(self.tab_signup, text="Sign up")
        self._build_tab_signup(self.tab_signup)

        # Make login the default selected
        nb.select(self.tab_login)

        # When login tab is shown, auto-start face login once
        nb.bind("<<NotebookTabChanged>>", lambda e: self._maybe_auto_face(nb))
        # Also trigger after initial layout
        self.root.after(250, lambda: self._maybe_auto_face(nb))

    # ===================== TAB: LOG-IN =====================
    def _build_tab_login(self, parent):
        info = ttk.Frame(parent)
        info.pack(fill=tk.X, pady=(0,10))
        ttk.Label(info, text="Look at the camera to log in.", style="Info.TLabel").pack(anchor="center")

        # Status label (no buttons per your spec)
        self.login_status = ttk.Label(parent, text="", foreground="#e74c3c", font=("Segoe UI", 10))
        self.login_status.pack(pady=(6,0))

    def _maybe_auto_face(self, nb):
        # Only run when Log-in tab is active and we haven't launched yet
        if nb.select() != str(self.tab_login):
            return
        # Prevent repeated spawns on tab flicker
        if getattr(self, "_face_login_running", False):
            return
        self._face_login_running = True
        self.login_status.config(text="Starting camera…")
        self.root.after(50, self._start_face_login_once)

    def _start_face_login_once(self):
        if not os.path.exists(self.recognize_py):
            self.login_status.config(text="Face recognizer not found.")
            self._face_login_running = False
            return

        # Run one-shot recognition with a visible window
        def worker():
            try:
                proc = subprocess.run(
                    [self.py_exec, self.recognize_py, "--once", "--json", "--timeout", "12", "--show"],
                    capture_output=True, text=True, cwd=self.face_dir
                )
                out_lines = (proc.stdout.strip().splitlines() or ["{}"])
                data = json.loads(out_lines[-1])
            except Exception as e:
                err_msg = f"Error: {e}"
                self.root.after(0, lambda m=err_msg: self._face_login_failed(m))
                return

            name = data.get("name")
            if not name:
                self.root.after(0, lambda: self._face_login_failed("No face match. Try again."))
                return

            # Lookup in DB
            student = self.student_manager.get_student(name)
            if not student:
                self.root.after(0, lambda: self._face_login_failed(f"Recognized '{name}', but no account found. Please Sign up."))
                return

            # Success → open dashboard
            def open_ok():
                self.student_manager.current_user = student
                self.root.destroy()
                self.open_dashboard()
            self.root.after(0, open_ok)

        threading.Thread(target=worker, daemon=True).start()

    def _face_login_failed(self, msg):
        self.login_status.config(text=msg)
        # Allow a single auto-retry after a short pause (still no buttons)
        def retry():
            self._face_login_running = False
            self._maybe_auto_face(self.tab_login.nametowidget(self.tab_login.master.select()))
        self.root.after(1200, retry)

    # ===================== TAB: SIGN-UP =====================
    def _build_tab_signup(self, parent):
        form = ttk.Frame(parent)
        form.pack(fill=tk.X)

        ttk.Label(form, text="Enter Your Full Name:", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(2, 4))
        self.name_entry = ttk.Entry(form, font=("Segoe UI", 11))
        self.name_entry.pack(fill=tk.X, pady=(0, 8), ipady=5)
        self.name_entry.focus()

        ttk.Label(form, text="Select Your English Level:", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(6, 4))
        self.level_var = tk.StringVar(value="A2")
        level_frame = ttk.Frame(form)
        level_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Radiobutton(level_frame, text="Pre-Intermediate (A2)", variable=self.level_var, value="A2").pack(side=tk.LEFT, padx=(0,10))
        ttk.Radiobutton(level_frame, text="Intermediate (B1)",     variable=self.level_var, value="B1").pack(side=tk.LEFT)

        # Only one button: NEW STUDENT
        self.btn_new_student = ttk.Button(form, text="NEW STUDENT", command=self.handle_registration, style="Purple.TButton")
        self.btn_new_student.pack(fill=tk.X, pady=(12, 4))

        # Hidden until registration completes
        self.btn_add_face = ttk.Button(form, text="Add Face Recognition", command=self.launch_gui_face_rec, style="Green.TButton")
        self.btn_add_face.pack(fill=tk.X, pady=(6, 0))
        self.btn_add_face.pack_forget()

        # error label (if needed)
        self.signup_status = ttk.Label(form, text="", foreground="#e74c3c", font=("Segoe UI", 9))
        self.signup_status.pack(pady=(6, 0))

    def handle_registration(self):
        name = self.name_entry.get().strip()
        if not name:
            self.signup_status.config(text="Please enter your full name")
            return

        if self.student_manager.get_student(name):
            self.signup_status.config(text="Student already exists. Please log in.")
            return

        new_student = {
            "name": name,
            "level": self.level_var.get(),
            "progress": {"reading": 0.0, "grammar": 0.0, "vocabulary": 0.0},
            "completed_lessons": [],
            "created_at": datetime.now().isoformat()
        }
        self.student_manager.db.insert(new_student)
        self.student_manager.current_user = new_student

        messagebox.showinfo("Welcome", f"Welcome {name}!\nYour account has been created.")
        # Stay on Sign-up tab and reveal Add Face Recognition
        self.btn_add_face.pack(fill=tk.X, pady=(6, 0))
        self.signup_status.config(text="Now add your face to enable quick login.")

    def launch_gui_face_rec(self):
        if not os.path.exists(self.gui_face_rec_py):
            messagebox.showerror("Face Tools", "gui_face_rec.py not found in Face_Recognition/")
            return
        try:
            subprocess.Popen([self.py_exec, self.gui_face_rec_py], cwd=self.face_dir)
        except Exception as e:
            messagebox.showerror("Face Tools", f"Failed to open: {e}")

    def open_dashboard(self):
        dashboard_window = tk.Toplevel(self.main_app.root)
        dashboard.Dashboard(dashboard_window, self.main_app, self.student_manager)
        dashboard_window.geometry("1000x800")
        dashboard_window.transient(self.main_app.root)
        dashboard_window.grab_set()

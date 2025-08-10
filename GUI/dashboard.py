import tkinter as tk
from tkinter import ttk, messagebox
from styles import configure_styles
import lesson
from tkinter import font as tkfont
from tinydb import Query
import random
import os


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("Segoe UI", 9))
        label.pack(ipadx=5, ipady=3)

    def hide_tip(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


class Dashboard:
    def __init__(self, root, main_app, student_manager):
        self.root = root
        self.main_app = main_app
        self.student_manager = student_manager
        
        self.root.title(f"Lingo - {student_manager.current_user['name']}")
        self.root.geometry("1000x700")
        self.root.minsize(900, 650)
        self.root.configure(bg="#f5f3ff")  # Light lavender background
        
        # Color scheme
        self.primary_color = "#6c5ce7"
        self.secondary_color = "#a29bfe"
        self.bg_color = "#f5f3ff"
        self.card_color = "#ffffff"
        self.text_color = "#2d3436"
        self.light_text = "#636e72"
        
        configure_styles()
        self._configure_custom_styles()
        
        # Create main frame early
        #self.main_frame = tk.Frame(root, bg="#6c5ce7")  # or your theme color
        #self.main_frame.pack(fill="both", expand=True)
        
        self.create_widgets()
        self.update_display()
        
    def _configure_custom_styles(self):
        style = ttk.Style()
        
        # Try using a clean modern font
        try:
            base_font = ("Poppins", 11)
            title_font = ("Poppins", 24, "bold")
            subtitle_font = ("Poppins", 14)
        except:
            base_font = ("Segoe UI", 11)
            title_font = ("Segoe UI", 24, "bold")
            subtitle_font = ("Segoe UI", 14)
        
        # General background
        style.configure("TFrame", background=self.bg_color)
        
        # Card style
        style.configure("DashboardCard.TFrame",
                        background=self.card_color,
                        relief="solid",
                        borderwidth=0)
        
        # Subject button style
        style.configure("Subject.TButton",
                        font=("Segoe UI", 13, "bold"),
                        padding=(20, 12),
                        width=25,
                        background=self.card_color,
                        foreground=self.text_color,
                        borderwidth=0,
                        relief="flat")
        style.map("Subject.TButton",
                  background=[("active", "#edeafc")],
                  foreground=[("active", self.primary_color)])
        
        # Logout button style
        style.configure("Accent.TButton",
                        font=("Segoe UI", 12, "bold"),
                        padding=(15, 8),
                        background=self.primary_color,
                        foreground="white",
                        borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#5649c0")],
                  foreground=[("active", "white")])
        
        # Progress bar style
        style.configure("Modern.Horizontal.TProgressbar",
                        thickness=14,
                        troughcolor="#edeafc",
                        background=self.primary_color)
        
        # Labels
        style.configure("Title.TLabel",
                        font=title_font,
                        foreground=self.primary_color,
                        background=self.bg_color)
        style.configure("Subtitle.TLabel",
                        font=subtitle_font,
                        foreground=self.light_text,
                        background=self.bg_color)
        style.configure("Section.TLabel",
                        font=("Segoe UI", 16, "bold"),
                        foreground=self.text_color,
                        background=self.card_color)
        style.configure("Progress.TLabel",
                        font=("Segoe UI", 11),
                        foreground=self.text_color,
                        background=self.card_color)
        
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=(30, 20))
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header (unchanged)
        header_frame = ttk.Frame(main_frame, height=100)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        header_frame.pack_propagate(False)
        
        header_content = ttk.Frame(header_frame)
        header_content.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        
        first_name = self.student_manager.current_user['name']
                
        ttk.Label(header_content,
                  text=f"Hello, {first_name}!",
                  style="Title.TLabel").pack(anchor=tk.W, pady=(5, 0))
        
        ttk.Label(header_content,
                  text="Buckle up - we're about to make English fun!",
                  style="Subtitle.TLabel").pack(anchor=tk.W, pady = (5,0))
        
        logout_btn = ttk.Button(header_frame,
                                text="Log Out",
                                command=self.logout,
                                style="Accent.TButton")
        logout_btn.pack(side=tk.RIGHT, padx=20, ipady=3)
        
        # Content frame
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # Progress card
        progress_card = ttk.Frame(content_frame, style="DashboardCard.TFrame", padding=25)
        progress_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15))
        
        ttk.Label(progress_card,
                  text="Your Learning Progress",
                  style="Section.TLabel").pack(anchor=tk.W, pady=(0, 20))
        
        self.progress_frame = ttk.Frame(progress_card)
        self.progress_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add the lessons completed & upcoming section here
        self.lessons_info_frame = ttk.Frame(progress_card)
        self.lessons_info_frame.pack(fill=tk.BOTH, expand=True, pady=(20, 0))

        ## User Level
        user = self.student_manager.current_user
        level_map = {"A2": "Pre-Intermediate", "B1": "Intermediate"}
        level_text = f"{user['level']} – {level_map.get(user['level'], '')}"


        # Lessons card (unchanged)
        lessons_card = ttk.Frame(content_frame, style="DashboardCard.TFrame", padding=25)
        lessons_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(15, 0))
        
        ttk.Label(lessons_card,
                  text=level_text + "'s Practice Modules",
                  style="Section.TLabel").pack(anchor=tk.W, pady=(0, 15))
                  
                
        button_frame = ttk.Frame(lessons_card)
        button_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Button(button_frame,
                   text="Reading Comprehension",
                   command=lambda: self.start_lesson("reading"),
                   style="Subject.TButton").pack(fill=tk.X, pady=10)
        
        ttk.Button(button_frame,
                   text="Grammar Mastery",
                   command=lambda: self.start_lesson("grammar"),
                   style="Subject.TButton").pack(fill=tk.X, pady=10)
        
        ttk.Button(button_frame,
                   text="Vocabulary Builder",
                   command=lambda: self.start_lesson("vocabulary"),
                   style="Subject.TButton").pack(fill=tk.X, pady=10)

        ttk.Button(button_frame,
                   text="Coming Soon!!",
                   command=lambda: self.start_lesson("#"),
                   style="Subject.TButton").pack(fill=tk.X, pady=10)
                   
        # Motivational message label at bottom
        self.motivation_label = ttk.Label(progress_card, style="Subtitle.TLabel", wraplength=400)
        self.motivation_label.pack(pady=(15, 0), anchor=tk.CENTER)

        
    
    def update_display(self):
        # Sync progress with completed lessons first
        self.student_manager.sync_progress_with_completed()
        # Clear and redraw progress bars
        for widget in self.progress_frame.winfo_children():
            widget.destroy()
        
        user = self.student_manager.current_user
        lesson_types = ['reading', 'grammar', 'vocabulary']

        for lt in lesson_types:
            folder = os.path.join(
                self.student_manager.lesson_manager.lessons_root,
                f"{user['level']} Level (Pre-Intermediate)" if user['level'] == "A2"
                else f"{user['level']} Level (Intermediate)",
                lt.capitalize()
            )
            total_lessons = len([f for f in os.listdir(folder) if f.endswith('.json')]) if os.path.isdir(folder) else 0

            completed_lessons = self.student_manager.lesson_manager.lessons_db.search(
                (Query().user == user['name']) & (Query().lesson_type == lt)
            )
            completed_count = len(completed_lessons)

            progress = (completed_count / total_lessons) if total_lessons > 0 else 0
            progress_percent = int(progress * 100)

            # Determine color based on progress percentage
            if progress_percent <= 30:
                progress_color = "#e74c3c"  # Red-ish
            elif 31 <= progress_percent <= 70:
                progress_color = "#e67e22"  # Orange-ish
            else:
                progress_color = "#27ae60"  # Green

            style_name = f"ProgressBar.{lt}.Horizontal.TProgressbar"
            style = ttk.Style()
            style.configure(style_name,
                            thickness=14,
                            troughcolor="#edeafc",
                            background=progress_color)

            # Create progress bar frame and widgets
            subject_frame = ttk.Frame(self.progress_frame, style="DashboardCard.TFrame")
            subject_frame.pack(fill=tk.X, pady=8)

            ttk.Label(subject_frame,
                      text=lt.upper(),
                      style="Progress.TLabel",
                      width=18,
                      anchor=tk.W,
                      foreground=self.primary_color).pack(side=tk.LEFT, padx=(0, 10))

            progress_bar = ttk.Progressbar(subject_frame,
                                           orient=tk.HORIZONTAL,
                                           style=style_name,
                                           value=progress_percent)
            progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Add tooltip to progress bar
            Tooltip(progress_bar, f"{completed_count} of {total_lessons} lessons completed")

            # Percentage label with bold if 100%
            font_weight = "bold" if progress_percent == 100 else "normal"
            perc_label = ttk.Label(subject_frame,
                                   text=f"{progress_percent}%",
                                   style="Progress.TLabel",
                                   foreground=progress_color,
                                   width=5)
            perc_label.pack(side=tk.RIGHT, padx=(10, 0))

            # Configure font weight dynamically
#             f = tkfont.nametofont(perc_label.cget("font")).copy()
#             f.configure(weight=font_weight)
#             perc_label.configure(font=f)
            try:
                f = tkfont.nametofont(perc_label.cget("font")).copy()
            except tk.TclError:
                # Create a new font if the named font doesn't exist
                current_font = perc_label.cget("font")
                f = tkfont.Font(font=current_font)

            f.configure(weight=font_weight)
            perc_label.configure(font=f)

        # Clear lessons info frame
        for widget in self.lessons_info_frame.winfo_children():
            widget.destroy()

        # Show lessons completed count and upcoming lessons per type
        for lt in lesson_types:
            completed_count = len([
                l for l in self.student_manager.lesson_manager.lessons_db.search(
                    (Query().user == user['name']) & (Query().lesson_type == lt)
                )
            ])

            folder = os.path.join(
                self.student_manager.lesson_manager.lessons_root,
                f"{user['level']} Level (Pre-Intermediate)" if user['level'] == "A2"
                else f"{user['level']} Level (Intermediate)",
                lt.capitalize()
            )
            total_lessons = len([f for f in os.listdir(folder) if f.endswith('.json')]) if os.path.isdir(folder) else 0

            next_lesson = self.student_manager.lesson_manager.get_lesson_by_type(user['level'], lt, user)
            next_title = next_lesson.get('title', '') if next_lesson else ''

            frame = ttk.Frame(self.lessons_info_frame, style="DashboardCard.TFrame", padding=10)
            frame.pack(fill=tk.X, pady=4)

            if completed_count == total_lessons and total_lessons > 0:
                completed_text = f"All {lt.capitalize()} Lessons Completed! 🎉"
                ttk.Label(frame,
                          text=completed_text,
                          style="Progress.TLabel",
                          foreground=self.primary_color).pack(anchor=tk.W)
                ttk.Label(frame,
                          text="",
                          style="Progress.TLabel").pack(anchor=tk.W)
            else:
                ttk.Label(frame,
                          text=f"{lt.capitalize()} Lessons Completed: {completed_count}",
                          style="Progress.TLabel",
                          foreground=self.primary_color).pack(anchor=tk.W)

                status_icon = "✅" if next_title else "🚫"
                next_text = f"{status_icon} Next {lt.capitalize()} Lesson: {next_title if next_title else 'No upcoming lesson'}"
                ttk.Label(frame,
                          text=next_text,
                          style="Progress.TLabel",
                          foreground=self.light_text).pack(anchor=tk.W)

        # Show motivational message randomly chosen from lesson_manager greetings
        greetings = self.student_manager.lesson_manager.GREETINGS
        first_name = user['name'].split()[0]
        message = random.choice(greetings).format(name=first_name)
        self.motivation_label.config(text=message)
        
        print(f"Lesson type: {lt}")
        print(f"Folder: {folder}")
        print(f"Total lessons found: {total_lessons}")
        print(f"Completed lessons count: {completed_count}")
        print(f"Progress percent: {progress_percent}")
            
    def start_lesson(self, lesson_type):       
            lesson_window = tk.Toplevel(self.root)
            lesson_window.title(f"Lingo - {lesson_type.capitalize()} Lesson")

            # Set the current lesson before creating the LessonScreen
            self.main_app.current_lesson = self.student_manager.lesson_manager.get_lesson_by_type(
                self.student_manager.current_user['level'],
                lesson_type,
                self.student_manager.current_user
            )

            lesson.LessonScreen(
                lesson_window,
                self.main_app,
                self.student_manager,
                lesson_type
            )
            lesson_window.geometry("900x700")
            lesson_window.transient(self.root)  # optional — keeps it on top but not modal
            # 🚫 Removed grab_set() — no more modal lock

    
    def logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to log out?"):
            self.student_manager.current_user = None
            self.root.destroy()
            self.main_app.root.deiconify()

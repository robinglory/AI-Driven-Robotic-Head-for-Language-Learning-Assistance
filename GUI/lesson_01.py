# lesson.py
import os
import json
import random
import threading
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import font as tkfont

from styles import configure_styles
from api_manager import APIManager  # fallback if needed

# ---------- Simple JSON helpers ----------
def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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
        self.current_lesson = main_app.current_lesson  # set by dashboard before opening

        # Use the SAME LLM pipeline as main.py (fast + streaming + hedge)
        self.llm = main_app.llm
        self._fallback_llm = None  # lazy: APIManager only if needed

        # Identify user/lesson for persistence
        self.user_id = str(self.student_manager.current_user.get("id", "default"))
        self.lesson_path = self.current_lesson.get("filepath", f"default_{lesson_type}")

        # Load persisted data
        self.conversation_data = load_json(self.CONVERSATIONS_JSON_PATH)
        self.students_data = load_json(self.STUDENTS_JSON_PATH)

        # Load or start fresh conversation
        self.conversation_history = self.conversation_data.get(self.user_id, {}).get(self.lesson_path, [])
        self.student_manager.conversation_history = self.conversation_history

        # Streaming plumbing
        self._stream_queue: queue.Queue = queue.Queue()
        self._stream_worker: threading.Thread | None = None
        self._streaming = False
        self._thinking_tagged = False
        self._thinking_start_index = None
        self._first_chunk_seen = False
        self._current_response_buffer = []  # accumulate streamed chunks

        # Window config
        self.root.title(f"Lingo - AI Personal English Teacher ({lesson_type.capitalize()} Section)")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg="#f8f9fa")

        # Fonts
        self.title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.content_font = tkfont.Font(family="Segoe UI", size=12)
        self.message_font = tkfont.Font(family="Segoe UI", size=11)

        configure_styles()
        self.create_widgets()
        self.load_lesson()

    # ---------- UI ----------
    def create_widgets(self):
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

        # Keep input row visible
        self.conversation_display = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            font=self.content_font,
            height=18,            # was 30; this avoids the input row being pushed out
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
        self.conversation_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)

        input_frame = ttk.Frame(main_frame, style="Input.TFrame")
        input_frame.pack(fill=tk.X)

        self.user_input = ttk.Entry(input_frame, font=("Segoe UI", 12))
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.handle_input)

        send_btn = ttk.Button(input_frame, text="Send", command=self.handle_input, style="Accent.TButton")
        send_btn.pack(side=tk.RIGHT)

        self.user_input.focus()

        # Replay prior conversation
        for msg in self.conversation_history:
            sender = "You" if msg["role"] == "user" else "Lingo"
            self.display_message(sender, msg["content"])

    def load_lesson(self):
        try:
            if not self.student_manager or not self.student_manager.current_user:
                raise ValueError("Student information not available")

            lesson = self.student_manager.lesson_manager.get_lesson_by_type(
                self.student_manager.current_user["level"],
                self.lesson_type,
                self.student_manager.current_user
            )
            if not lesson:
                messagebox.showerror("Error", "Lesson content not found")
                self.root.destroy()
                return

            self.current_lesson_path = lesson.get("filepath")
            self.student_manager.current_lesson = lesson

            self.display_lesson_content(lesson)
            self.display_personalized_welcome(lesson)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load lesson: {str(e)}")
            self.root.destroy()

    def display_lesson_content(self, lesson):
        self.display_message("system", "=== LESSON CONTENT ===", is_lesson=True)
        self.display_message("system", f"Lesson: {lesson.get('title', 'English Practice')}", is_lesson=True)
        if "objective" in lesson:
            self.display_message("system", f"Objective: {lesson['objective']}", is_lesson=True)
        if "text" in lesson and lesson["text"]:
            self.display_message("system", lesson["text"], is_lesson=True)

    def display_personalized_welcome(self, lesson):
        student_name = self.student_manager.current_user["name"].split()[0]
        praise = random.choice([
            "This is going to really boost your English skills!",
            "I'm excited to help you master this important area!",
            "You're making great progress by working on this!",
            "This lesson will take your English to the next level!",
        ])
        welcome_msg = (
            f"Hello {student_name}! I'm Lingo, Your Personal AI English Teacher.\n"
            f"Now it's time to learn {self.lesson_type.capitalize()}.\n"
            f"{praise}\n"
            f"Today we'll be working on: {lesson.get('title', 'English Practice')}\n"
        )
        if "objective" in lesson:
            welcome_msg += f"\nOur goal is: {lesson['objective']}"
        self.display_message("Lingo", welcome_msg)

    def display_message(self, sender, message, is_lesson=False):
        self.conversation_display.configure(state='normal')
        if is_lesson:
            self.conversation_display.insert(tk.END, f"\n{message}\n", "content")
        else:
            tag = "ai" if sender == "Lingo" else "user"
            self.conversation_display.insert(tk.END, f"\n{sender}: ", tag)
            self.conversation_display.insert(tk.END, f"{message}\n", "message")
        self.conversation_display.see(tk.END)
        self.conversation_display.configure(state='disabled')

    def return_to_dashboard(self):
        try:
            if getattr(self, "current_lesson_path", None) and self.student_manager:
                self.student_manager.lesson_manager.record_lesson_completion(
                    self.student_manager.current_user["name"],
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

            try:
                self.root.grab_release()
            except:
                pass

            if isinstance(self.root, tk.Toplevel):
                self.root.destroy()

            if hasattr(self.main_app, "dashboard"):
                self.main_app.dashboard.update_display()
            elif hasattr(self.main_app, "show_dashboard"):
                self.main_app.show_dashboard()

            if hasattr(self.main_app, "root"):
                self.main_app.root.deiconify()
                self.main_app.root.lift()
                self.main_app.root.focus_force()
        except Exception as e:
            print(f"Error returning to dashboard: {e}")

    # ---------- Streaming helpers ----------
    def _append_stream_text(self, text: str):
        self.conversation_display.configure(state='normal')
        self.conversation_display.insert(tk.END, text, "message")
        self.conversation_display.see(tk.END)
        self.conversation_display.configure(state='disabled')

    def _replace_thinking_header_if_needed(self):
        """Replace 'Lingo (Thinking…): ' with 'Lingo: ' on first token."""
        if self._first_chunk_seen or not self._thinking_tagged or self._thinking_start_index is None:
            return
        try:
            self.conversation_display.configure(state='normal')
            start = self._thinking_start_index
            end = f"{start} + {len('Lingo (Thinking…): ')}c"
            self.conversation_display.delete(start, end)
            self.conversation_display.insert(start, "Lingo: ", "ai")
            self.conversation_display.configure(state='disabled')
            self._first_chunk_seen = True
        except Exception:
            pass

    def _drain_stream_queue(self):
        try:
            while True:
                chunk = self._stream_queue.get_nowait()
                if chunk is None:
                    self._streaming = False
                    # Ensure header is correct even if no tokens arrived
                    if not self._first_chunk_seen and self._thinking_tagged and self._thinking_start_index:
                        self._replace_thinking_header_if_needed()
                    self._append_stream_text("\n")
                    self.root.config(cursor="")

                    # Persist full assistant message to history
                    full_assistant = "".join(self._current_response_buffer).strip()
                    if full_assistant:
                        self.student_manager.conversation_history.append(
                            {"role": "assistant", "content": full_assistant}
                        )

                    # Save updated conversation
                    self.conversation_data.setdefault(self.user_id, {})
                    self.conversation_data[self.user_id][self.lesson_path] = self.student_manager.conversation_history
                    save_json(self.CONVERSATIONS_JSON_PATH, self.conversation_data)
                    self._current_response_buffer.clear()
                    return
                else:
                    if not self._first_chunk_seen:
                        self._replace_thinking_header_if_needed()
                    self._current_response_buffer.append(chunk)
                    self._append_stream_text(chunk)
        except queue.Empty:
            pass
        if self._streaming:
            self.root.after(15, self._drain_stream_queue)

    # ---------- Input handling ----------
    def handle_input(self, event=None):
        if self._streaming:
            return

        user_input = self.user_input.get().strip()
        if not user_input:
            return

        self.display_message("You", user_input)
        self.user_input.delete(0, tk.END)

        try:
            # Build lesson-aware prompts that FORCE answers from lesson text only
            lesson = self.student_manager.current_lesson or {}
            lesson_title = lesson.get("title", "")
            lesson_type = self.lesson_type
            lesson_objective = lesson.get("objective", "")
            lesson_text = lesson.get("text", "") or ""

            LESSON_SLICE_LIMIT = 1200
            lesson_slice = lesson_text[:LESSON_SLICE_LIMIT]

            system_rules = (
                "You are Lingo, a personal English tutor. "
                "You are currently teaching a specific LESSON to the student. "
                "CRITICAL:\n"
                "1) Base your responses ONLY on the provided LESSON TEXT below. Do not use outside knowledge.\n"
                "2) If the answer is not in the LESSON TEXT yet, say: \"The lesson text doesn’t say yet.\" and guide the student to the relevant part.\n"
                "3) Keep answers short (≤2 sentences, ≤60 words) and end with one simple question.\n"
                "4) Avoid the '*' character.\n"
                "5) Do not invent names or facts not present in the LESSON TEXT.\n"
                "6) Match the lesson type (Reading/Grammar/Vocabulary):\n"
                "   - Reading: give a brief, text‑based explanation + one comprehension question.\n"
                "   - Grammar: explain the rule using examples from the text; avoid new rules not in text.\n"
                "   - Vocabulary: define/illustrate only words appearing in the text.\n"
            )

            lesson_header = (
                f"LESSON METADATA:\n"
                f"Title: {lesson_title}\n"
                f"Type: {lesson_type}\n"
                f"Objective: {lesson_objective}\n"
            )

            lesson_payload = (
                "LESSON TEXT (authoritative; use this ONLY):\n"
                "<<<BEGIN LESSON TEXT>>>\n"
                f"{lesson_slice}\n"
                "<<<END LESSON TEXT>>>\n"
            )

            # Cap history to last 6 messages (3 pairs) to keep latency low
            recent_history = self.student_manager.conversation_history[-6:] if self.student_manager.conversation_history else []

            messages = [
                {"role": "system", "content": system_rules},
                {"role": "system", "content": lesson_header + "\n" + lesson_payload},
            ]
            messages.extend(recent_history)
            messages.append({"role": "user", "content": user_input})

            # Start streaming
            self._streaming = True
            self._first_chunk_seen = False
            self._current_response_buffer.clear()
            self.root.config(cursor="watch")

            # Show status header
            self.conversation_display.configure(state='normal')
            self._thinking_start_index = self.conversation_display.index(tk.END)
            self.conversation_display.insert(tk.END, "\nLingo (Thinking…): ", "ai")
            self.conversation_display.configure(state='disabled')
            self.conversation_display.see(tk.END)
            self._thinking_tagged = True

            def worker():
                try:
                    # Prefer main_app.llm streaming; fallback to APIManager if missing for any reason
                    if hasattr(self.llm, "stream_ai_response"):
                        gen = self.llm.stream_ai_response(messages=messages)
                    else:
                        if self._fallback_llm is None:
                            self._fallback_llm = APIManager()
                        gen = self._fallback_llm.stream_ai_response(messages=messages)

                    for chunk in gen:
                        self._stream_queue.put(chunk)
                    self._stream_queue.put(None)
                except Exception as e:
                    self._stream_queue.put(f"\n[Error: {e}]")
                    self._stream_queue.put(None)

            self._stream_worker = threading.Thread(target=worker, daemon=True)
            self._stream_worker.start()
            self.root.after(15, self._drain_stream_queue)

            # Add user message to history immediately
            self.student_manager.conversation_history.append({"role": "user", "content": user_input})

        except Exception as e:
            print(f"Error in lesson: {str(e)}")
            self.display_message("Lingo", "Let me check the material... One moment please!")

    def _generate_system_prompt(self, context):
        """Deprecated: kept for compatibility."""
        return "You are Lingo, a personal English tutor. Use only the provided lesson text."

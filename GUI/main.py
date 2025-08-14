# main.py
import os
import sys
import threading
import queue
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext

from dotenv import load_dotenv
from openai import OpenAI

# UI modules (paths adjusted for your current structure)
from styles import configure_styles
from login import LoginScreen
from student_manager import StudentManager
from lesson_manager import LessonManager

load_dotenv()

SOFT_TIMEOUT_SECONDS = 6.0
DEFAULT_MAX_TOKENS = 96
DEFAULT_STOP = ["\n\n", "Question:", "Q:"]

class LLMHandler:
    """
    General chat LLM with streaming + hedged requests (winner-only).
    """
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
        self.current_provider = 0  # Start with first
        self.client = self._create_client()

    def _create_client(self, provider_idx=None):
        idx = self.current_provider if provider_idx is None else provider_idx
        p = self.api_providers[idx]
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=p["api_key"],
            timeout=20.0
        )
        client._client.headers.update(p["headers"])
        return client

    def _switch_provider(self):
        self.current_provider = (self.current_provider + 1) % len(self.api_providers)
        print(f"Switching to {self.api_providers[self.current_provider]['name']}...")
        self.client = self._create_client()

    # ---------- Blocking (legacy fallback) ----------
    def get_ai_response(self, message=None, conversation_history=None, lesson_context=None, messages=None):
        """
        Kept for compatibility (non-streaming). Prefer stream_ai_response for UI.
        """
        if messages is None:
            if message is None:
                raise ValueError("Either message or messages must be provided")

            # Build system prompt
            if lesson_context:
                system_msg = (
                    f"You are Lingo teaching {lesson_context['student_name']} (Level: {lesson_context['student_level']}). "
                    f"Current Lesson: {lesson_context['lesson_title']}\n"
                    f"Objective: {lesson_context['lesson_objective']}\n"
                    "Guidelines:\n"
                    "1. Reference the lesson content\n"
                    "2. Personalize explanations\n"
                    "3. Keep responses focused\n"
                    "4. Keep responses short (<=2 sentences, <=60 words) and end with one short question.\n"
                )
            else:
                system_msg = (
                    "You are Lingo, a friendly AI English Teacher. "
                    "Have natural conversations and help with general English questions. "
                    "Keep responses <=2 sentences (<=60 words) and end with one short question. "
                    "Avoid the '*' character."
                )

            messages = [{"role": "system", "content": system_msg}]
            if conversation_history:
                messages.extend(conversation_history[-4:])  # last 4 messages only
            messages.append({"role": "user", "content": message})

        p = self.api_providers[self.current_provider]
        try:
            resp = self.client.chat.completions.create(
                model=p["model"],
                messages=messages,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=0.7,
                stop=DEFAULT_STOP
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error with {p['name']}: {e}")
            self._switch_provider()
            return "I'm having trouble connecting. Please try again."

    # ---------- Streaming + Hedge (winner-only) ----------
    def stream_ai_response(self, message=None, conversation_history=None, lesson_context=None, messages=None):
        """
        Yields text chunks as they arrive.
        Races two providers; ONLY the first provider that emits a token continues streaming.
        The loser is signaled to stop immediately.
        """
        import time
        import threading
        import queue

        # Build messages if not supplied
        if messages is None:
            if message is None:
                raise ValueError("Either message or messages must be provided")

            if lesson_context:
                system_msg = (
                    f"You are Lingo teaching {lesson_context['student_name']} (Level: {lesson_context['student_level']}). "
                    f"Current Lesson: {lesson_context['lesson_title']}\n"
                    f"Objective: {lesson_context['lesson_objective']}\n"
                    "Guidelines:\n"
                    "1. Reference the lesson content\n"
                    "2. Personalize explanations\n"
                    "3. Keep responses focused\n"
                    "4. Keep responses short (<=2 sentences, <=60 words) and end with one short question.\n"
                )
            else:
                system_msg = (
                    "You are Lingo, a friendly AI English Teacher. "
                    "Keep responses <=2 sentences (<=60 words) and end with one short question. "
                    "Avoid the '*' character."
                )

            messages = [{"role": "system", "content": system_msg}]
            if conversation_history:
                messages.extend(conversation_history[-4:])
            messages.append({"role": "user", "content": message})

        # Pick two providers to race
        idx_a = self.current_provider
        idx_b = (self.current_provider + 1) % len(self.api_providers)

        out_q: queue.Queue = queue.Queue()
        winner_lock = threading.Lock()
        winner_idx = {"value": None}  # becomes idx_a or idx_b when first token appears
        stop_flags = {idx_a: threading.Event(), idx_b: threading.Event()}
        sentinels_needed = 2  # expect two worker terminations

        def stream_from_provider(provider_idx: int):
            p = self.api_providers[provider_idx]
            client = self._create_client(provider_idx)
            try:
                stream = client.chat.completions.create(
                    model=p["model"],
                    messages=messages,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    temperature=0.7,
                    stop=DEFAULT_STOP,
                    stream=True
                )
                for event in stream:
                    # If told to stop (lost the race), exit immediately
                    if stop_flags[provider_idx].is_set():
                        break

                    delta = getattr(event.choices[0].delta, "content", None)
                    if not delta:
                        continue

                    # Decide winner on the very first emitted token
                    with winner_lock:
                        if winner_idx["value"] is None:
                            winner_idx["value"] = provider_idx
                            other_idx = idx_a if provider_idx == idx_b else idx_b
                            stop_flags[other_idx].set()  # stop the loser
                        elif winner_idx["value"] != provider_idx:
                            # We lost the race → exit immediately
                            break

                    # We are the winner → forward token
                    out_q.put(delta)

            except Exception as e:
                # Surface the error only if no winner yet (helps with diagnosing total failures)
                with winner_lock:
                    if winner_idx["value"] is None:
                        out_q.put(f"\n[Error: {p['name']} failed: {e}]")
                        # Let the other worker continue trying
            finally:
                # Signal this worker is done
                out_q.put((provider_idx, None))

        def soft_timeout_referee():
            """If no one has produced tokens in ~6s, pick idx_a by default."""
            start = time.time()
            while (time.time() - start) < SOFT_TIMEOUT_SECONDS:
                with winner_lock:
                    if winner_idx["value"] is not None:
                        return
                time.sleep(0.01)
            with winner_lock:
                if winner_idx["value"] is None:
                    winner_idx["value"] = idx_a
                    stop_flags[idx_b].set()

        ta = threading.Thread(target=stream_from_provider, args=(idx_a,), daemon=True)
        tb = threading.Thread(target=stream_from_provider, args=(idx_b,), daemon=True)
        tr = threading.Thread(target=soft_timeout_referee, daemon=True)
        tr.start(); ta.start(); tb.start()

        finished = 0
        while finished < sentinels_needed:
            item = out_q.get()
            if isinstance(item, tuple) and item[1] is None:
                finished += 1
                continue
            yield item


class MainAIChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Lingo - AI English Teacher")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg="#f8f9fa")

        configure_styles()

        self.llm = LLMHandler()
        self.lesson_manager = LessonManager(llm_handler=self.llm)
        self.student_manager = StudentManager(lesson_manager=self.lesson_manager)

        self.current_lesson = None
        self.conversation_history = []
        self.login_window = None
        self.dashboard_window = None

        self.create_widgets()

        # streaming plumbing
        self._stream_queue: queue.Queue = queue.Queue()
        self._stream_worker: threading.Thread | None = None
        self._streaming = False

    def show_dashboard(self):
        if self.dashboard_window and self.dashboard_window.winfo_exists():
            self.dashboard_window.lift()
            return
        self.root.withdraw()
        dashboard_root = tk.Toplevel(self.root)
        self.dashboard_window = dashboard_root

        from dashboard import Dashboard
        Dashboard(dashboard_root, self, self.student_manager)

        dashboard_root.geometry("1000x700")
        dashboard_root.protocol("WM_DELETE_WINDOW", self.return_to_main)
        dashboard_root.transient(self.root)
        dashboard_root.grab_set()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=(20, 15))
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(main_frame, style="Header.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 20), ipady=10)

        ttk.Label(header_frame, text="Lingo - AI English Teacher", style="Header.TLabel").pack(side=tk.LEFT, padx=10)

        login_btn = ttk.Button(header_frame, text="Login to Personal Tutor Mode", command=self.open_login, style="Accent.TButton")
        login_btn.pack(side=tk.RIGHT, padx=10)

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

        input_frame = ttk.Frame(main_frame, style="Input.TFrame")
        input_frame.pack(fill=tk.X)

        self.user_input = ttk.Entry(input_frame, font=("Segoe UI", 12))
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.send_message)

        send_btn = ttk.Button(input_frame, text="Send", command=self.send_message, style="Accent.TButton")
        send_btn.pack(side=tk.RIGHT)

        self.display_message("Lingo", "Hello! I'm Lingo, your AI English Teacher. How can I help you today?")

    def display_message(self, sender, message):
        self.chat_display.configure(state='normal')
        self.chat_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("user", foreground="#00b894", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)
        self.chat_display.insert(tk.END, f"{sender}: ", "ai" if sender == "Lingo" else "user")
        self.chat_display.insert(tk.END, f"{message}\n\n", "message")
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')

    def _append_stream_text(self, text: str):
        """Tkinter-safe: called from the UI thread via .after() loop."""
        self.chat_display.configure(state='normal')
        self.chat_display.insert(tk.END, text, "message")
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')

    def _drain_stream_queue(self):
        """UI loop that drains the queue and updates the text box."""
        try:
            while True:
                chunk = self._stream_queue.get_nowait()
                if chunk is None:
                    self._streaming = False
                    # finalize with a newline for spacing
                    self._append_stream_text("\n\n")
                    self.root.config(cursor="")
                    return
                self._append_stream_text(chunk)
        except queue.Empty:
            pass
        # continue draining while streaming
        if self._streaming:
            self.root.after(15, self._drain_stream_queue)

    def send_message(self, event=None):
        if self._streaming:
            return  # prevent overlapping sends

        message = self.user_input.get().strip()
        if not message:
            return

        # Show user message immediately
        self.display_message("You", message)
        self.user_input.delete(0, tk.END)

        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": message})

        # Local “fast mode” shortcuts (no LLM)
        simple = self.get_simple_response(message.lower())
        if simple:
            self.display_message("Lingo", simple)
            self.conversation_history.append({"role": "assistant", "content": simple})
            return

        # Prepare lesson context if logged in
        lesson_context = None
        if getattr(self.student_manager, "current_user", None):
            if self.current_lesson:
                lesson_context = {
                    "student_name": self.student_manager.current_user["name"],
                    "student_level": self.student_manager.current_user["level"],
                    "lesson_title": self.current_lesson.get("title", ""),
                    "lesson_objective": self.current_lesson.get("objective", "")
                }

        # Start streaming worker
        self._streaming = True
        self.root.config(cursor="watch")

        # Prepend the "Lingo: " label and start streaming text right after it
        self.chat_display.configure(state='normal')
        self.chat_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)
        self.chat_display.insert(tk.END, "Lingo: ", "ai")
        self.chat_display.configure(state='disabled')
        self.chat_display.see(tk.END)

        def worker():
            try:
                for chunk in self.llm.stream_ai_response(
                    message=message,
                    conversation_history=self.conversation_history,
                    lesson_context=lesson_context
                ):
                    self._stream_queue.put(chunk)
                # Finish
                self._stream_queue.put(None)
            except Exception as e:
                self._stream_queue.put(f"\n[Error: {e}]")
                self._stream_queue.put(None)

        self._stream_worker = threading.Thread(target=worker, daemon=True)
        self._stream_worker.start()
        self.root.after(15, self._drain_stream_queue)

    def get_simple_response(self, message):
        import random
        if any(word in message for word in ["hello", "hi", "hey"]):
            return random.choice([
                "Hello there! How can I help you today?",
                "Hi! What would you like to know?",
                "Greetings! What's on your mind?"
            ])
        elif any(word in message for word in ["how are you", "how's it going"]):
            return "I'm doing well and ready to help! How are you?"
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
        self.login_window = tk.Toplevel(self.root)
        self.login_window.protocol("WM_DELETE_WINDOW", self.on_login_close)
        LoginScreen(self.login_window, self)
        self.login_window.geometry("400x300")
        self.login_window.transient(self.root)
        self.login_window.grab_set()

    def on_login_close(self):
        if self.login_window:
            self.login_window.destroy()
            self.login_window = None

    def return_to_main(self):
        if self.dashboard_window:
            self.dashboard_window.destroy()
            self.dashboard_window = None
        self.root.deiconify()


if __name__ == "__main__":
    root = tk.Tk()
    app = MainAIChat(root)
    root.mainloop()

#!/usr/bin/env python3
# gui_face_rec.py — Simple GUI wrapper for capture → train → recognize
# Folder: /home/robinglory/Desktop/Thesis/Face_Recognition
# Requires the three scripts we set up earlier:
#   capture_faces.py, train_lbph.py, recognize_live.py
#
# Run:
#   source venv/bin/activate
#   python gui_face_rec.py

import os, sys, json, subprocess, threading, time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---------- Paths ----------
ROOT = os.path.abspath(os.path.dirname(__file__))
VENVDIR = os.path.join(ROOT, "venv")
PY = os.path.join(VENVDIR, "bin", "python") if os.path.exists(VENVDIR) else sys.executable
CAPTURE = os.path.join(ROOT, "capture_faces.py")
TRAIN   = os.path.join(ROOT, "train_lbph.py")
RUNREC  = os.path.join(ROOT, "recognize_live.py")
FACEDB  = os.path.join(ROOT, "FaceDB")
MODEL_DIR = os.path.join(FACEDB, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "lbph.yml")
LABELS_PATH = os.path.join(MODEL_DIR, "labels.json")

# Ensure base dirs
os.makedirs(FACEDB, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

# ---------- Helpers ----------
def count_images_for(name: str) -> int:
    p = os.path.join(FACEDB, name)
    if not os.path.isdir(p):
        return 0
    return sum(1 for fn in os.listdir(p) if fn.lower().endswith(".png"))

def ensure_scripts_exist():
    missing = []
    for p in (CAPTURE, TRAIN, RUNREC):
        if not os.path.exists(p):
            missing.append(os.path.basename(p))
    if missing:
        messagebox.showerror("Missing files", "These scripts are missing:\n- " + "\n- ".join(missing))
        return False
    return True

def run_subprocess(args, on_done=None, on_output=None):
    """
    Run a subprocess in a thread; stream lines to on_output; call on_done(returncode).
    """
    def _worker():
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                if on_output:
                    on_output(line.rstrip())
            rc = proc.wait()
            if on_done:
                on_done(rc)
        except Exception as e:
            if on_output:
                on_output(f"[ERROR] {e}")
            if on_done:
                on_done(1)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Face Recognition — Capture • Train • Test")
        self.geometry("880x560")
        self.minsize(820, 520)

        self.style = ttk.Style(self)
        # Neat theme-ish styling
        self.configure(bg="#101418")
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#101418")
        self.style.configure("Title.TLabel", foreground="#E6EDF3", background="#101418", font=("Segoe UI", 18, "bold"))
        self.style.configure("Sub.TLabel", foreground="#8AA0AF", background="#101418", font=("Segoe UI", 11))
        self.style.configure("TLabel", foreground="#E6EDF3", background="#101418", font=("Segoe UI", 10))
        self.style.configure("TButton", padding=10, font=("Segoe UI", 10, "bold"), background="#1F6FEB", foreground="white")
        self.style.map("TButton", background=[("active", "#2A7FFF")])
        self.style.configure("Ghost.TButton", padding=10, font=("Segoe UI", 10, "bold"), background="#30363D", foreground="#E6EDF3")
        self.style.map("Ghost.TButton", background=[("active", "#3B434C")])
        self.style.configure("Danger.TButton", padding=10, font=("Segoe UI", 10, "bold"), background="#A40E26", foreground="white")
        self.style.map("Danger.TButton", background=[("active", "#C51634")])
        self.style.configure("Card.TFrame", background="#0D1117", relief="flat")
        self.style.configure("Status.TLabel", foreground="#9ECE6A", background="#0D1117", font=("Consolas", 10))

        # top
        header = ttk.Frame(self, style="TFrame")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="Face Recognition — Test Bench", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Step 1: Capture  •  Step 2: Train  •  Step 3: Recognize  (same camera/cascade as your detector)", style="Sub.TLabel").pack(anchor="w")

        main = ttk.Frame(self, style="TFrame")
        main.pack(fill="both", expand=True, padx=16, pady=8)

        left = ttk.Frame(main, style="Card.TFrame")
        left.pack(side="left", fill="y", padx=(0,8), pady=0)
        right = ttk.Frame(main, style="Card.TFrame")
        right.pack(side="right", fill="both", expand=True, padx=(8,0), pady=0)

        # Left panel — controls
        lf = ttk.LabelFrame(left, text=" Controls ", padding=12)
        lf.pack(fill="y", padx=12, pady=12)

        self.name_var = tk.StringVar()
        ttk.Label(lf, text="Student Name").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(lf, textvariable=self.name_var, width=22)
        name_entry.grid(row=1, column=0, sticky="we", pady=(2,8))
        name_entry.focus()

        self.count_var = tk.StringVar(value="Images: 0 / 50")
        ttk.Label(lf, textvariable=self.count_var).grid(row=2, column=0, sticky="w", pady=(0,8))

        self.btn_capture = ttk.Button(lf, text="Capture Faces", command=self.on_capture)
        self.btn_capture.grid(row=3, column=0, sticky="we", pady=4)

        self.btn_open_person = ttk.Button(lf, text="Open Person Folder", style="Ghost.TButton", command=self.open_person_folder)
        self.btn_open_person.grid(row=4, column=0, sticky="we", pady=4)

        ttk.Separator(lf).grid(row=5, column=0, sticky="we", pady=8)

        self.train_status = tk.StringVar(value="Model: not trained")
        ttk.Label(lf, textvariable=self.train_status).grid(row=6, column=0, sticky="w", pady=(0,6))

        self.btn_train = ttk.Button(lf, text="Train Model (LBPH)", command=self.on_train, state="disabled")
        self.btn_train.grid(row=7, column=0, sticky="we", pady=4)

        self.btn_open_models = ttk.Button(lf, text="Open Models Folder", style="Ghost.TButton", command=self.open_models_folder)
        self.btn_open_models.grid(row=8, column=0, sticky="we", pady=4)

        ttk.Separator(lf).grid(row=9, column=0, sticky="we", pady=8)

        self.btn_test = ttk.Button(lf, text="Run Recognition", command=self.on_test, state="disabled")
        self.btn_test.grid(row=10, column=0, sticky="we", pady=4)

        self.btn_quit = ttk.Button(lf, text="Quit", style="Danger.TButton", command=self.destroy)
        self.btn_quit.grid(row=11, column=0, sticky="we", pady=(18,0))

        for i in range(0, 12):
            lf.grid_rowconfigure(i, pad=2)
        lf.grid_columnconfigure(0, weight=1)

        # Right panel — logs / status
        rf = ttk.LabelFrame(right, text=" Output ", padding=10)
        rf.pack(fill="both", expand=True, padx=12, pady=12)

        self.txt = tk.Text(rf, height=10, background="#0D1117", foreground="#D1D5DA",
                           insertbackground="#D1D5DA", borderwidth=0, highlightthickness=0)
        self.txt.pack(fill="both", expand=True)
        self.txt_tag_info = ("info",)
        self.txt.tag_config("info", foreground="#9CDCFE")
        self.txt_tag_ok = ("ok",)
        self.txt.tag_config("ok", foreground="#9ECE6A")
        self.txt_tag_err = ("err",)
        self.txt.tag_config("err", foreground="#F38BA8")

        # refreshers
        self.after(500, self.refresh_state)

    # ---------- UI helpers ----------
    def log(self, s, tag="info"):
        self.txt.insert("end", s + "\n", tag)
        self.txt.see("end")

    def refresh_state(self):
        name = self.name_var.get().strip()
        cnt = count_images_for(name) if name else 0
        self.count_var.set(f"Images: {cnt} / 50")
        # Enable training if enough images exist (for any person OR this one?)
        # UX: enable when the currently typed name has >=50
        self.btn_train.configure(state=("normal" if cnt >= 50 else "disabled"))
        # Recognition enabled if model files exist
        can_test = os.path.exists(MODEL_PATH) and os.path.exists(LABELS_PATH)
        self.btn_test.configure(state=("normal" if can_test else "disabled"))
        # Model status
        if can_test:
            self.train_status.set("Model: ready")
        else:
            self.train_status.set("Model: not trained")
        self.after(500, self.refresh_state)

    def open_person_folder(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("No name", "Enter a student name first.")
            return
        p = os.path.join(FACEDB, name)
        os.makedirs(p, exist_ok=True)
        self.open_folder(p)

    def open_models_folder(self):
        self.open_folder(MODEL_DIR)

    def open_folder(self, path):
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                os.startfile(path)
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    # ---------- Actions ----------
    def on_capture(self):
        if not ensure_scripts_exist():
            return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("No name", "Enter a student name before capturing.")
            return
        os.makedirs(os.path.join(FACEDB, name), exist_ok=True)
        self.log(f"[capture] Starting capture for: {name}")
        args = [PY, CAPTURE, name]
        def on_output(line):
            if "Saved" in line or "Using cascade" in line:
                self.log(line, tag="ok")
            elif "[ERROR]" in line or "❌" in line:
                self.log(line, tag="err")
            else:
                self.log(line)
        def on_done(rc):
            self.log(f"[capture] exited with code {rc}", tag=("ok" if rc==0 else "err"))
        run_subprocess(args, on_done=on_done, on_output=on_output)

    def on_train(self):
        if not ensure_scripts_exist():
            return
        self.log("[train] Training LBPH model…")
        args = [PY, TRAIN]
        def on_output(line):
            if "Training LBPH" in line or "Saved model" in line or "Saved labels" in line:
                self.log(line, tag="ok")
            elif "❌" in line or "[ERROR]" in line:
                self.log(line, tag="err")
            else:
                self.log(line)
        def on_done(rc):
            if rc == 0 and os.path.exists(MODEL_PATH):
                self.log("[train] ✅ Training complete.", tag="ok")
            else:
                self.log("[train] ❌ Training failed.", tag="err")
        run_subprocess(args, on_done=on_done, on_output=on_output)

    def on_test(self):
        if not ensure_scripts_exist():
            return
        if not (os.path.exists(MODEL_PATH) and os.path.exists(LABELS_PATH)):
            messagebox.showwarning("Model not ready", "Train the model first.")
            return
        self.log("[test] Starting live recognition…")
        args = [PY, RUNREC]
        def on_output(line):
            # LBPH output isn’t verbose by default; just show cascade/model checks
            if "Using cascade" in line:
                self.log(line, tag="ok")
            elif "❌" in line or "[ERROR]" in line:
                self.log(line, tag="err")
            else:
                self.log(line)
        def on_done(rc):
            self.log(f"[test] exited with code {rc}", tag=("ok" if rc==0 else "err"))
        run_subprocess(args, on_done=on_done, on_output=on_output)

if __name__ == "__main__":
    App().mainloop()

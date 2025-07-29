import tkinter as tk
from tkinter import ttk

def configure_styles():
    style = ttk.Style()
    style.theme_use("clam")
    
    # Base styles
    style.configure(".", background="#f0f2f5")
    style.configure("TFrame", background="#f0f2f5")
    style.configure("TLabel", background="#f0f2f5", font=("Helvetica", 12))
    style.configure("TButton", font=("Helvetica", 12), padding=6)
    style.configure("TEntry", font=("Helvetica", 12), padding=6)
    
    # Accent button style
    style.configure("Accent.TButton",
                   font=("Helvetica", 12, "bold"),
                   foreground="white",
                   background="#3498db",
                   padding=8)
    style.map("Accent.TButton",
              foreground=[('pressed', 'white'), ('active', 'white')],
              background=[('pressed', '#2980b9'), ('active', '#2980b9')])
    
    # Lesson button style
    style.configure("Lesson.TButton",
                   font=("Helvetica", 12),
                   padding=10,
                   width=15)
    
    # Progress bar style
    style.configure("Horizontal.TProgressbar",
                   thickness=20,
                   troughcolor="#ecf0f1",
                   background="#2ecc71",
                   lightcolor="#2ecc71",
                   darkcolor="#27ae60")
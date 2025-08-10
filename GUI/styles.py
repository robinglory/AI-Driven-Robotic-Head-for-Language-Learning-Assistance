import tkinter as tk
from tkinter import ttk

def configure_styles():
    style = ttk.Style()
    style.theme_use("clam")
    
    # Color palette
    bg_color = "#f8f9fa"
    primary_color = "#6c5ce7"
    secondary_color = "#a29bfe"
    accent_color = "#00cec9"
    text_color = "#2d3436"
    
    # Base styles
    style.configure(".", 
                   background=bg_color,
                   foreground=text_color)
    style.configure("TFrame", 
                   background=bg_color)
    style.configure("TLabel", 
                   background=bg_color, 
                   font=("Segoe UI", 11),
                   foreground=text_color)
    style.configure("TButton", 
                   font=("Segoe UI", 11), 
                   padding=8,
                   relief="flat",
                   background=secondary_color,
                   foreground="white")
    style.configure("TEntry", 
                   font=("Segoe UI", 11), 
                   padding=8,
                   fieldbackground="white")
    
    # Accent button style
    style.configure("Accent.TButton",
                   font=("Segoe UI", 11, "bold"),
                   foreground="white",
                   background=primary_color,
                   padding=10,
                   borderwidth=0)
    style.map("Accent.TButton",
              foreground=[('pressed', 'white'), ('active', 'white')],
              background=[('pressed', '#5649c0'), ('active', '#5649c0')])
    
    # Chat display style
    style.configure("Chat.TFrame",
                   background="white",
                   relief="solid",
                   borderwidth=1)
    
    # Input style
    style.configure("Input.TFrame",
                   background=bg_color)
    
    # Header style
    style.configure("Header.TFrame",
                   background=primary_color)
    style.configure("Header.TLabel",
                   background=primary_color,
                   foreground="white",
                   font=("Segoe UI", 14, "bold"))
    
    # Lesson button style
    style.configure("Lesson.TButton",
                   font=("Segoe UI", 11),
                   padding=10,
                   width=15,
                   background=accent_color)
    
    # Progress bar style
    style.configure("Horizontal.TProgressbar",
                   thickness=20,
                   troughcolor="#ecf0f1",
                   background=accent_color,
                   lightcolor=accent_color,
                   darkcolor="#00b894")
    
    # Scrollbar style
    style.configure("Vertical.TScrollbar",
                   arrowsize=15,
                   troughcolor=bg_color)
    
    # Add these to your configure_styles() function
    style.configure("Card.TFrame", 
                   background="white",
                   relief="solid",
                   borderwidth=0,
                   bordercolor="#dfe6e9",
                   padding=20)

    style.configure("TEntry.field", 
                   fieldbackground="#f5f6fa",
                   bordercolor="#dfe6e9",
                   lightcolor="#dfe6e9",
                   darkcolor="#dfe6e9")

    style.map("TEntry.field",
             fieldbackground=[("focus", "#ffffff")],
             bordercolor=[("focus", "#6c5ce7")])

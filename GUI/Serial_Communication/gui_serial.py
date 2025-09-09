#!/usr/bin/env python3
# gui_lingo.py — minimal Tk GUI to drive your Arduino controller
# Works on Raspberry Pi 4 with pyserial installed.

import tkinter as tk
from tkinter import ttk, messagebox
import threading, time
import serial
from serial.tools import list_ports

DEFAULT_BAUD = 115200
READ_TIMEOUT = 0.1

def list_serial_ports():
    ports = list(list_ports.comports())
    # Prefer ACM (UNO official) then USB (CH340 clones)
    ordered = sorted(ports, key=lambda p: (("ACM" not in p.device), ("USB" not in p.device), p.device))
    return ordered

class UnoSerial:
    def __init__(self, on_line=None):
        self.ser = None
        self.reader = None
        self._stop = threading.Event()
        self.on_line = on_line

    def connect(self, port, baud=DEFAULT_BAUD):
        self.close()
        try:
            self.ser = serial.Serial(port, baud, timeout=READ_TIMEOUT, write_timeout=1,
                                     rtscts=False, dsrdtr=False)
        except Exception as e:
            self.ser = None
            raise

        # First open usually resets the UNO → give it time & clear boot text
        time.sleep(1.5)
        try:
            self.ser.reset_input_buffer()
            # Deassert DTR/RTS so we don't keep resetting on future opens
            try:
                self.ser.setDTR(False)
                self.ser.setRTS(False)
            except Exception:
                pass
        except Exception:
            pass

        self._stop.clear()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                b = self.ser.read(1) if self.ser else b""
            except Exception:
                break
            if not b:
                continue
            if b in (b"\n", b"\r"):
                if buf:
                    line = buf.decode(errors="replace")
                    if self.on_line:
                        try: self.on_line(line)
                        except Exception: pass
                    buf = b""
            else:
                buf += b

    def send(self, text):
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Not connected")
        line = (text.strip() + "\n").encode()
        self.ser.write(line)

    def close(self):
        self._stop.set()
        if self.reader:
            try: self.reader.join(timeout=0.5)
            except Exception: pass
        self.reader = None
        if self.ser:
            try: self.ser.close()
            except Exception: pass
        self.ser = None

# ---------------- GUI ----------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lingo Controller")
        self.geometry("740x480")

        self.serial = UnoSerial(on_line=self._append_line_threadsafe)

        # Top bar: port & baud & connect
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="Port:").pack(side="left")
        self.port_cmb = ttk.Combobox(top, width=22, state="readonly")
        self.port_cmb.pack(side="left", padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=4)

        ttk.Label(top, text="Baud:").pack(side="left", padx=(12,0))
        self.baud_cmb = ttk.Combobox(top, width=8, values=[115200, 57600, 9600], state="readonly")
        self.baud_cmb.set(str(DEFAULT_BAUD))
        self.baud_cmb.pack(side="left", padx=4)

        self.connect_btn = ttk.Button(top, text="Connect", command=self.toggle_connect)
        self.connect_btn.pack(side="left", padx=6)

        # Log window
        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=8, pady=(0,8))
        self.log = tk.Text(mid, height=14, wrap="none")
        self.log_scroll = ttk.Scrollbar(mid, command=self.log.yview)
        self.log.configure(yscrollcommand=self.log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        self.log_scroll.pack(side="right", fill="y")

        # Commands row 1
        row1 = ttk.Frame(self); row1.pack(fill="x", padx=8, pady=4)
        self.btn_listen = ttk.Button(row1, text="Listen", command=lambda: self.send_cmd("listen"))
        self.btn_think  = ttk.Button(row1, text="Think",  command=lambda: self.send_cmd("think"))
        self.btn_talk   = ttk.Button(row1, text="Talk",   command=lambda: self.send_cmd("talk"))
        self.btn_stop   = ttk.Button(row1, text="Stop",   command=lambda: self.send_cmd("stop"))
        self.btn_park   = ttk.Button(row1, text="Park",   command=lambda: self.send_cmd("park"))
        self.btn_help   = ttk.Button(row1, text="Help",   command=lambda: self.send_cmd("help"))

        for b in (self.btn_listen, self.btn_think, self.btn_talk, self.btn_stop, self.btn_park, self.btn_help):
            b.pack(side="left", padx=6)

        # Commands row 2 (extras)
        row2 = ttk.Frame(self); row2.pack(fill="x", padx=8, pady=4)
        self.btn_listen_left  = ttk.Button(row2, text="Listen Left",  command=lambda: self.send_cmd("listen_left"))
        self.btn_listen_right = ttk.Button(row2, text="Listen Right", command=lambda: self.send_cmd("listen_right"))
        self.btn_listen_left.pack(side="left", padx=6)
        self.btn_listen_right.pack(side="left", padx=6)

        # Settings row (set_* commands)
        row3 = ttk.Frame(self); row3.pack(fill="x", padx=8, pady=6)

        ttk.Label(row3, text="total_listen ms").pack(side="left")
        self.e_total_listen = ttk.Entry(row3, width=8); self.e_total_listen.insert(0, "8000")
        self.e_total_listen.pack(side="left", padx=4)
        ttk.Button(row3, text="Set", command=self.set_total_listen).pack(side="left", padx=6)

        ttk.Label(row3, text="total_think ms").pack(side="left", padx=(12,0))
        self.e_total_think = ttk.Entry(row3, width=8); self.e_total_think.insert(0, "8000")
        self.e_total_think.pack(side="left", padx=4)
        ttk.Button(row3, text="Set", command=self.set_total_think).pack(side="left", padx=6)

        ttk.Label(row3, text="talk_cycle ms").pack(side="left", padx=(12,0))
        self.e_talk_cycle = ttk.Entry(row3, width=8); self.e_talk_cycle.insert(0, "15000")
        self.e_talk_cycle.pack(side="left", padx=4)
        ttk.Button(row3, text="Set", command=self.set_talk_cycle).pack(side="left", padx=6)

        ttk.Label(row3, text="return ms").pack(side="left", padx=(12,0))
        self.e_return = ttk.Entry(row3, width=8); self.e_return.insert(0, "8000")
        self.e_return.pack(side="left", padx=4)
        ttk.Button(row3, text="Set", command=self.set_return).pack(side="left", padx=6)

        self.set_buttons_enabled(False)
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- helpers ----
    def _append_line_threadsafe(self, s: str):
        # Called from reader thread: schedule on Tk main loop
        self.after(0, lambda: self._append_line(s))

    def _append_line(self, s: str):
        self.log.insert("end", s + "\n")
        self.log.see("end")

    def refresh_ports(self):
        ports = list_serial_ports()
        items = [p.device for p in ports]
        self.port_cmb["values"] = items
        if items:
            # preselect ACM first
            acm = [p for p in items if "ACM" in p]
            self.port_cmb.set(acm[0] if acm else items[0])
        else:
            self.port_cmb.set("")
        self._append_line("(ports) " + (", ".join(items) if items else "none"))

    def toggle_connect(self):
        if self.serial.ser and self.serial.ser.is_open:
            self.serial.close()
            self._append_line("[PI] disconnected")
            self.connect_btn.config(text="Connect")
            self.set_buttons_enabled(False)
            return

        port = self.port_cmb.get().strip()
        if not port:
            messagebox.showerror("No port", "Select a serial port first.")
            return
        try:
            baud = int(self.baud_cmb.get())
        except:
            baud = DEFAULT_BAUD
        try:
            self.serial.connect(port, baud=baud)
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))
            return
        self._append_line(f"[PI] connected {port} @ {baud}")
        self.connect_btn.config(text="Disconnect")
        self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for b in (self.btn_listen, self.btn_think, self.btn_talk, self.btn_stop,
                  self.btn_park, self.btn_help, self.btn_listen_left, self.btn_listen_right):
            b.config(state=state)

    def send_cmd(self, cmd: str):
        try:
            self.serial.send(cmd)
            self._append_line(f"[PI] -> {cmd}")
        except Exception as e:
            messagebox.showerror("Send failed", str(e))

    # ---- setters ----
    def set_total_listen(self):
        v = self.e_total_listen.get().strip()
        if not v.isdigit():
            messagebox.showerror("Value error", "Enter milliseconds (e.g., 8000)")
            return
        self.send_cmd(f"set_total_listen {v}")

    def set_total_think(self):
        v = self.e_total_think.get().strip()
        if not v.isdigit():
            messagebox.showerror("Value error", "Enter milliseconds (e.g., 8000)")
            return
        self.send_cmd(f"set_total_think {v}")

    def set_talk_cycle(self):
        v = self.e_talk_cycle.get().strip()
        if not v.isdigit():
            messagebox.showerror("Value error", "Enter milliseconds (e.g., 15000)")
            return
        self.send_cmd(f"set_talk_cycle {v}")

    def set_return(self):
        v = self.e_return.get().strip()
        if not v.isdigit():
            messagebox.showerror("Value error", "Enter milliseconds (e.g., 8000)")
            return
        self.send_cmd(f"set_return {v}")

    def on_close(self):
        try:
            self.serial.close()
        finally:
            self.destroy()

if __name__ == "__main__":
    App().mainloop()

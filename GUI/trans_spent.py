# Plays ONE random filler .wav during STT "Transcribing…" after a 3s delay.
# This version uses a separate PROCESS so the delay & playback are not blocked
# by Python threads while Faster-Whisper is running.

import os
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, List
import multiprocessing as mp

def _child_delayed_play(delay_sec: float, wav_path: str, device: Optional[str], stop_flag: mp.Event):
    """
    Child process:
      1) wait delay_sec (unless stop_flag set)
      2) start 'aplay' for wav_path (once)
      3) exit when aplay finishes or stop_flag is set (then terminate aplay)
    """
    aplay = shutil.which("aplay")
    if not aplay or not os.path.isfile(wav_path):
        return

    # Phase 1: delayed arm
    t0 = time.time()
    while (time.time() - t0) < delay_sec:
        if stop_flag.is_set():
            # canceled before delay elapsed
            return
        time.sleep(0.02)

    # Phase 2: start playback once
    cmd = [aplay, "-q"]
    if device:
        cmd += ["-D", device]
    cmd += [wav_path]

    try:
        # Start aplay; keep a handle so we can stop early if asked
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return

    # Phase 3: monitor for stop or natural completion
    try:
        while proc.poll() is None:
            if stop_flag.is_set():
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
            time.sleep(0.05)
    finally:
        # Ensure process is gone
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


class TransSpent:
    """
    Manager that picks a random filler clip and plays it ONCE if STT takes longer than delay_sec.
    - No immediate repeat: excludes the last used clip from the next pick.
    - Uses a child PROCESS for the delayed start and playback (robust under CPU/GIL load).
    """

    def __init__(self, audio_dir: str, device: Optional[str] = None, seed: Optional[int] = None):
        self.audio_dir = Path(audio_dir)
        self.device = device
        if seed is not None:
            random.seed(seed)

        # discover wav files
        self._files: List[Path] = sorted(self.audio_dir.glob("*.wav"))
        if not self._files:
            raise RuntimeError(f"No .wav files found in {self.audio_dir}")

        # selection state
        self._bag: List[int] = []
        self._last_used: Optional[int] = None

        # runtime state (process-based)
        self._proc: Optional[mp.Process] = None
        self._stop_flag: Optional[mp.Event] = None
        self._active: bool = False      # armed or playing
        self._playing: bool = False     # best-effort flag (True after child actually starts)

        # precheck aplay
        self._aplay = shutil.which("aplay")
        if not self._aplay:
            raise RuntimeError("aplay not found. Install with: sudo apt-get install alsa-utils")

        # mp start method: fork is default on Linux; keep defaults

    # -------- selection helpers --------
    def _refill_bag(self):
        idxs = list(range(len(self._files)))
        random.shuffle(idxs)
        # avoid immediate repeat at round boundary
        if self._last_used is not None and idxs and idxs[0] == self._last_used:
            for i in range(1, len(idxs)):
                if idxs[i] != self._last_used:
                    idxs[0], idxs[i] = idxs[i], idxs[0]
                    break
        self._bag = idxs

    def _pick_clip_index(self) -> int:
        if not self._bag:
            self._refill_bag()
        # also avoid immediate repeat if possible
        if self._last_used is not None and len(self._bag) > 1 and self._bag[0] == self._last_used:
            for i in range(1, len(self._bag)):
                if self._bag[i] != self._last_used:
                    self._bag[0], self._bag[i] = self._bag[i], self._bag[0]
                    break
        return self._bag.pop(0)

    # -------- public API --------
    def start_for_transcribing(self, delay_sec: float = 3.0):
        """
        Arm a delayed single-shot playback in a child process.
        If stop() is called before the delay expires, nothing plays.
        """
        if self._active:
            # already armed/playing; ignore double-starts
            return

        clip_idx = self._pick_clip_index()
        self._last_used = clip_idx
        wav_path = str(self._files[clip_idx])

        # child control
        stop_flag = mp.Event()
        proc = mp.Process(
            target=_child_delayed_play,
            args=(delay_sec, wav_path, self.device, stop_flag),
            daemon=True
        )
        proc.start()

        # record state
        self._proc = proc
        self._stop_flag = stop_flag
        self._active = True
        self._playing = False  # we won't know exactly when aplay begins; remains False (informational)
        print(f"[FILLER] armed delay={delay_sec:.1f}s (clip={Path(wav_path).name})")

    def stop(self):
        """
        Cancel pending start or stop an in-progress playback.
        Safe to call multiple times.
        """
        if not self._active:
            return

        # signal child to stop
        try:
            if self._stop_flag is not None:
                self._stop_flag.set()
        except Exception:
            pass

        # give the child a moment to exit cleanly
        try:
            if self._proc is not None and self._proc.is_alive():
                self._proc.join(timeout=0.5)
        except Exception:
            pass

        # forcefully terminate if still alive (rare)
        try:
            if self._proc is not None and self._proc.is_alive():
                self._proc.terminate()
        except Exception:
            pass

        # clear state
        self._proc = None
        self._stop_flag = None
        self._active = False
        self._playing = False
        print("[FILLER] stop")

    def is_running(self) -> bool:
        """True if the child process exists and is alive (armed or playing)."""
        return bool(self._proc and self._proc.is_alive())

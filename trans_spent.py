"""
trans_spent.py
--------------
Play exactly ONE natural-sounding "thinking" filler phrase during STT transcription,
by streaming text into an existing Piper pipeline (NO extra `aplay`, so no ALSA conflicts).

Public API:
    ts = TransSpent(speak_callable, phrases=None, seed=None)
    ts.start_for_transcribing(delay_sec=3.0)   # arm a one-shot filler after 3s
    ts.stop()                                  # stop if pending/playing (safe to call multiple times)
    ts.is_running() -> bool                    # True if the worker is alive

`speak_callable` must be a function like PiperEngine.say_chunk(text: str, final: bool),
i.e., it accepts text and a boolean indicating sentence end. In your app, pass:
    self._tts.say_chunk

You can override `phrases` with your own list[str]. A non-repeating "bag" shuffle is used
so the same phrase won't play twice in a row.
"""

from __future__ import annotations
import threading
import time
import random
from typing import Callable, List, Optional


# --- Default filler phrases (≈ 10–14 seconds each on typical TTS pacing) ---
DEFAULT_FILLERS: List[str] = [
    "Hmm… let me think about that for a moment. I want to make sure I understand what you said and find a clear way to help.",
    "Alright, I’m going to consider your question carefully. Give me a second to connect the ideas and find a helpful example.",
    "Interesting point… I’m thinking it through step by step so I can explain it simply and correctly for you.",
    "Let me pause and reflect on the best way to answer this. I want it to be accurate and easy to follow.",
    "Okay, I’m reviewing what you said in my head. I’ll organize my thoughts so the explanation makes sense.",
    "Good question! I’m going to check a few details in my memory and then I’ll share a useful explanation.",
    "One moment… I’m putting the pieces together. I want to give you a clear answer with a short example.",
    "Let’s think this through. I’ll consider the grammar and the meaning so I can guide you step by step.",
    "Alright, I’m searching for the best way to explain this. A simple approach should make it much clearer.",
    "Hold on a second… I’m comparing a few possibilities so I can pick the most helpful explanation for you.",
    "I’m thinking aloud here: I want to check the context and then suggest a neat way to practice it.",
    "Give me just a moment while I reason it out. I’ll provide a short tip you can use right away.",
    "Let me make sure I understood your intention correctly, then I’ll craft a clear and friendly answer.",
    "I’m piecing together the rules and a quick example so the idea becomes easier to remember.",
    "Okay, thinking… I’ll keep it short, practical, and focused on what helps you most right now.",
    "Let me take a breath and line up a simple explanation, then we’ll try a quick practice question.",
    "I’m working through the meaning and the best phrasing so it sounds natural in everyday English.",
    "One second… I’ll check the nuances and then give you a concise, easy-to-apply explanation.",
    "Thinking this through… I’ll choose the clearest path and share a tip to avoid common mistakes.",
    "Alright, almost there. I’ll wrap these ideas into a short, friendly answer you can use immediately."
]


class TransSpent:
    """
    Streams one random filler phrase into an existing TTS pipeline after a delay.
    - Uses a background thread (no heavy CPU).
    - Chunked delivery with a stop flag for quick interruption.
    - No immediate repeat (bag shuffle).
    """

    def __init__(
        self,
        speak_callable: Callable[[str, bool], None],
        phrases: Optional[List[str]] = None,
        seed: Optional[int] = None,
        words_per_chunk: int = 6,
        inter_chunk_pause: float = 0.10
    ):
        """
        :param speak_callable: function(text:str, final:bool) → None (e.g., PiperEngine.say_chunk)
        :param phrases: optional custom list of filler phrases; defaults to DEFAULT_FILLERS
        :param seed: optional seed for deterministic shuffle/no-repeat behavior
        :param words_per_chunk: how many words to accumulate per TTS chunk
        :param inter_chunk_pause: small pause between chunk writes, seconds
        """
        if seed is not None:
            random.seed(seed)
        self._speak = speak_callable
        self._phrases = list(phrases) if phrases else list(DEFAULT_FILLERS)

        if not self._phrases:
            raise ValueError("TransSpent requires at least one filler phrase.")

        # no-repeat bag
        self._bag: list[int] = []
        self._last_used: Optional[int] = None

        # runtime
        self._thr: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._active_lock = threading.Lock()
        self._running = False

        # chunking config
        self._words_per_chunk = max(2, int(words_per_chunk))
        self._inter_chunk_pause = max(0.0, float(inter_chunk_pause))

    # ---------- public API ----------
    def start_for_transcribing(self, delay_sec: float = 3.0) -> None:
        """
        Arm a delayed, one-shot filler. If stop() is called before delay elapses,
        nothing is spoken. If called during playback, the phrase halts promptly.
        """
        with self._active_lock:
            if self._running:
                return
            self._running = True
            self._stop.clear()

        clip_idx = self._pick_index()
        self._last_used = clip_idx
        phrase = self._phrases[clip_idx]

        t = threading.Thread(
            target=self._worker,
            args=(delay_sec, phrase),
            daemon=True
        )
        self._thr = t
        t.start()
        print(f"[FILLER] armed delay={delay_sec:.1f}s (phrase idx={clip_idx})")

    def stop(self) -> None:
        """
        Stop pending/playing filler. Safe to call multiple times.
        """
        self._stop.set()
        with self._active_lock:
            self._running = False
        print("[FILLER] stop")

    def is_running(self) -> bool:
        return self._thr is not None and self._thr.is_alive()

    # ---------- internals ----------
    def _worker(self, delay_sec: float, phrase: str) -> None:
        # delay stage (polling so we can be canceled)
        start = time.time()
        while (time.time() - start) < delay_sec:
            if self._stop.is_set():
                self._end()
                return
            time.sleep(0.02)

        # speak in small chunks, respecting stop flag
        try:
            self._speak_phrase_chunked(phrase)
        finally:
            self._end()

    def _speak_phrase_chunked(self, text: str) -> None:
        """
        Stream 'text' into Piper in small chunks.
        IMPORTANT: force the *first* flush to be final=True so Piper starts speaking right away.
        """
        words = text.strip().split()
        buf: list[str] = []
        count = 0
        punct_final = (".", "?", "!", "…")
        started = False  # <-- first-flush guard

        def flush(final: bool) -> None:
            nonlocal started
            piece = " ".join(buf).strip()
            if not piece:
                buf.clear()
                return
            # Force the *first* flush to end with newline so Piper starts synthesizing
            if not started:
                final = True
                started = True
            try:
                # send to Piper: newline if final=True, space if False
                self._speak(piece, final)
            except Exception as e:
                print("[FILLER] speak error:", e)
            finally:
                buf.clear()
            print(f"[FILLER] flush(final={final}) -> {piece!r}")


        for w in words:
            if self._stop.is_set():
                break
            buf.append(w)
            count += 1
            # sentence boundary?
            is_sentence_end = w.endswith(punct_final)
            # Flush either at a sentence end or every N words,
            # but *always* as final=True, so we emit a newline each time.
            if is_sentence_end or count >= self._words_per_chunk:
                flush(final=True)
                count = 0
            # tiny yield so we don't hog CPU
            if self._stop.wait(self._inter_chunk_pause):
                break

        # Always finalize any tail that’s still buffered (even if stop() was hit)
        if buf:
            flush(final=True)

            
    def _pick_index(self) -> int:
        if not self._bag:
            idxs = list(range(len(self._phrases)))
            random.shuffle(idxs)
            # avoid immediate repeat at bag boundary
            if self._last_used is not None and idxs and idxs[0] == self._last_used:
                for i in range(1, len(idxs)):
                    if idxs[i] != self._last_used:
                        idxs[0], idxs[i] = idxs[i], idxs[0]
                        break
            self._bag = idxs
        # also avoid immediate repeat if possible within bag
        if self._last_used is not None and len(self._bag) > 1 and self._bag[0] == self._last_used:
            for i in range(1, len(self._bag)):
                if self._bag[i] != self._last_used:
                    self._bag[0], self._bag[i] = self._bag[i], self._bag[0]
                    break
        return self._bag.pop(0)

    def _end(self) -> None:
        with self._active_lock:
            self._running = False

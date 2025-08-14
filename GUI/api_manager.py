# api_manager.py
import os
import threading
import queue
from typing import Generator, List, Dict, Optional
from openai import OpenAI

SOFT_TIMEOUT_SECONDS = 6.0  # soft timeout to pick the faster provider in the hedge
DEFAULT_MAX_TOKENS = 96
DEFAULT_STOP = ["\n\n", "Question:", "Q:"]  # encourage short, snappy replies

class APIManager:
    """
    Lesson-mode LLM client for your Tkinter app.
    Adds:
      - streaming via .stream_ai_response(messages)
      - hedged requests (race the first two providers; first to stream wins)
      - token limits + stop sequences for faster responses
    """
    def __init__(self):
        self.api_providers = [
            {
                "name": "Qwen3 Coder",
                "api_key": os.getenv("QWEN_API_KEY"),
                "model": "qwen/qwen3-coder:free",
                "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo Language Tutor"},
            },
            {
                "name": "Mistral 7B",
                "api_key": os.getenv("MISTRAL_API_KEY"),
                "model": "mistralai/mistral-7b-instruct:free",
                "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo Language Tutor"},
            },
            {
                "name": "GPT-OSS-20B",
                "api_key": os.getenv("GPT_OSS_API_KEY"),
                "model": "openai/gpt-oss-20b:free",
                "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo Language Tutor"},
            },
        ]
        self.current_provider_index = 0
        self.client = self._create_client()  # default client; streaming uses per-thread clients

    def _create_client(self, provider_idx: Optional[int] = None) -> OpenAI:
        idx = self.current_provider_index if provider_idx is None else provider_idx
        provider = self.api_providers[idx]
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=provider["api_key"],
            timeout=20.0,  # keep global timeout larger; hedge uses soft timeout
        )
        client._client.headers.update(provider["headers"])
        return client

    def switch_to_backup(self):
        self.current_provider_index = (self.current_provider_index + 1) % len(self.api_providers)
        new_provider = self.api_providers[self.current_provider_index]
        print(f"Lingo: Switching to {new_provider['name']}...")
        self.client = self._create_client()

    def get_current_model(self):
        return self.api_providers[self.current_provider_index]["model"]

    # ---------- Blocking (non-streaming) fallback ----------
    def get_ai_response(self, messages, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        """Keep a blocking method in case you need it anywhere."""
        provider = self.api_providers[self.current_provider_index]
        try:
            resp = self.client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                stop=DEFAULT_STOP,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error with {provider['name']}: {str(e)}")
            self.switch_to_backup()
            raise

    # ---------- Streaming + Hedge (winner-only) ----------
    def stream_ai_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
        hedge: bool = True,
    ) -> Generator[str, None, None]:
        """
        Yields text chunks as they arrive.
        If hedge=True, races two providers and ONLY streams from the first to emit a token.
        """
        import time

        stop = stop or DEFAULT_STOP

        if not hedge or len(self.api_providers) < 2:
            yield from self._stream_from_provider(self.current_provider_index, messages, max_tokens, temperature, stop)
            return

        idx_a = self.current_provider_index
        idx_b = (self.current_provider_index + 1) % len(self.api_providers)

        out_q: queue.Queue = queue.Queue()
        winner_lock = threading.Lock()
        winner_idx = {"value": None}
        stop_flags = {idx_a: threading.Event(), idx_b: threading.Event()}
        sentinels_needed = 2

        def worker(provider_idx: int):
            p = self.api_providers[provider_idx]
            client = self._create_client(provider_idx)
            try:
                stream = client.chat.completions.create(
                    model=p["model"],
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop,
                    stream=True,
                )
                for event in stream:
                    if stop_flags[provider_idx].is_set():
                        break
                    delta = getattr(event.choices[0].delta, "content", None)
                    if not delta:
                        continue
                    with winner_lock:
                        if winner_idx["value"] is None:
                            winner_idx["value"] = provider_idx
                            other_idx = idx_a if provider_idx == idx_b else idx_b
                            stop_flags[other_idx].set()
                        elif winner_idx["value"] != provider_idx:
                            break
                    out_q.put(delta)
            except Exception as e:
                with winner_lock:
                    if winner_idx["value"] is None:
                        out_q.put(f"\n[Error: {p['name']} failed: {e}]")
            finally:
                out_q.put((provider_idx, None))

        def arbiter():
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

        ta = threading.Thread(target=worker, args=(idx_a,), daemon=True)
        tb = threading.Thread(target=worker, args=(idx_b,), daemon=True)
        tm = threading.Thread(target=arbiter, daemon=True)
        tm.start(); ta.start(); tb.start()

        finished = 0
        while finished < sentinels_needed:
            item = out_q.get()
            if isinstance(item, tuple) and item[1] is None:
                finished += 1
                continue
            yield item

    def _stream_from_provider(
        self,
        provider_idx: int,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        stop: List[str],
    ) -> Generator[str, None, None]:
        """Single‑provider streaming (no hedge)."""
        provider = self.api_providers[provider_idx]
        client = self._create_client(provider_idx)
        stream = client.chat.completions.create(
            model=provider["model"],
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            stream=True,
        )
        for event in stream:
            delta = getattr(event.choices[0].delta, "content", None)
            if delta:
                yield delta

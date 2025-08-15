# key_manager.py
import json, os, threading

DEFAULT_KEYS_PATH = os.path.join(os.path.dirname(__file__), "keys.json")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

class KeyManager:
    """
    Manages multiple OpenRouter account profiles, each with its own API keys.
    - keys.json holds a list of profiles.
    - settings.json remembers which profile is active.
    """

    def __init__(self, keys_path: str = DEFAULT_KEYS_PATH):
        self._lock = threading.Lock()
        self.keys_path = keys_path
        self.settings_path = SETTINGS_PATH
        self.profiles = []      # list of dicts
        self.active_index = 0   # which profile is active
        self._load_profiles()
        self._load_active_index()

    def _load_profiles(self):
        if not os.path.exists(self.keys_path):
            # Fallback: build a single profile from environment (backward compatible)
            self.profiles = [{
                "label": "ENV_DEFAULT",
                "QWEN_API_KEY": os.getenv("QWEN_API_KEY", ""),
                "MISTRAL_API_KEY": os.getenv("MISTRAL_API_KEY", ""),
                "GPT_OSS_API_KEY": os.getenv("GPT_OSS_API_KEY", "")
            }]
            return
        with open(self.keys_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "profiles" not in data:
            raise ValueError("keys.json must contain a top-level 'profiles' list.")
        self.profiles = data["profiles"]
        if not self.profiles:
            raise ValueError("keys.json contains no profiles.")

    def _load_active_index(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    s = json.load(f)
                self.active_index = int(s.get("active_profile_index", 0)) % len(self.profiles)
                return
            except Exception:
                pass
        self.active_index = 0
        self._persist_active_index()

    def _persist_active_index(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({"active_profile_index": self.active_index}, f, indent=2)
        except Exception:
            pass  # non-fatal

    # ----- Public API -----
    def list_labels(self):
        return [p.get("label", f"Profile {i+1}") for i, p in enumerate(self.profiles)]

    def get_active_label(self):
        return self.profiles[self.active_index].get("label", f"Profile {self.active_index+1}")

    def get_keys(self):
        """Return the 3 OpenRouter keys for the current profile as a dict."""
        with self._lock:
            return {
                "QWEN_API_KEY": self.profiles[self.active_index].get("QWEN_API_KEY", ""),
                "MISTRAL_API_KEY": self.profiles[self.active_index].get("MISTRAL_API_KEY", ""),
                "GPT_OSS_API_KEY": self.profiles[self.active_index].get("GPT_OSS_API_KEY", "")
            }

    def switch_to(self, idx: int):
        with self._lock:
            self.active_index = int(idx) % len(self.profiles)
            self._persist_active_index()

    def next_profile(self):
        with self._lock:
            self.active_index = (self.active_index + 1) % len(self.profiles)
            self._persist_active_index()
            return self.active_index

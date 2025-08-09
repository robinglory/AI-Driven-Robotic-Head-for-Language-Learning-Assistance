from openai import OpenAI
import os

class APIManager:
    def __init__(self):
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.minstral_api_key = os.getenv("MINSTRAL_API_KEY")
        self.current_model = "qwen/qwen3-coder:free"
        self.current_key = self.deepseek_api_key
        self.client = self._create_client()
        
    def _create_client(self):
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.current_key,
            timeout=10.0
        )
        client._client.headers = {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "Lingo Language Tutor"
        }
        return client
    
    def switch_to_backup(self):
        print("Lingo: Switching to backup API key (Mistral)...")
        self.current_key = self.minstral_api_key
        self.current_model = "mistralai/mistral-7b-instruct:free"
        self.client = self._create_client()
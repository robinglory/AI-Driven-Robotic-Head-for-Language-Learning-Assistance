from openai import OpenAI
import os

class APIManager:
    def __init__(self):
        self.api_providers = [
            {
                "name": "Qwen3 Coder",
                "api_key": os.getenv("QWEN_API_KEY"),
                "model": "qwen/qwen3-coder:free",
                "headers": {
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Lingo Language Tutor"
                }
            },
            {
                "name": "Mistral 7B",
                "api_key": os.getenv("MISTRAL_API_KEY"),
                "model": "mistralai/mistral-7b-instruct:free",
                "headers": {
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Lingo Language Tutor"
                }
            },
            {
                "name": "GPT-OSS-20B",
                "api_key": os.getenv("GPT_OSS_API_KEY"),
                "model": "openai/gpt-oss-20b:free",
                "headers": {
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Lingo Language Tutor"
                }
            }
        ]
        self.current_provider_index = 0
        self.client = self._create_client()
        
    def _create_client(self):
        provider = self.api_providers[self.current_provider_index]
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=provider["api_key"],
            timeout=20.0  # Increased timeout for free models
        )
        # Apply headers to the client
        client._client.headers.update(provider["headers"])
        return client
    
    def switch_to_backup(self):
        self.current_provider_index = (self.current_provider_index + 1) % len(self.api_providers)
        new_provider = self.api_providers[self.current_provider_index]
        print(f"Lingo: Switching to {new_provider['name']}...")
        self.client = self._create_client()
        
    def get_current_model(self):
        return self.api_providers[self.current_provider_index]["model"]
    
    def get_ai_response(self, messages):
        """New method to handle the complete API call"""
        try:
            provider = self.api_providers[self.current_provider_index]
            response = self.client.chat.completions.create(
                model=provider["model"],
                messages=messages,
                max_tokens=200,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error with {provider['name']}: {str(e)}")
            self.switch_to_backup()
            raise  # Re-raise the exception to handle in the main class
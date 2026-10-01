from app.llm.base import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1"):
        super().__init__(name="groq", api_key=api_key, base_url=base_url)

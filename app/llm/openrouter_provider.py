from app.llm.base import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        super().__init__(name="openrouter", api_key=api_key, base_url=base_url)

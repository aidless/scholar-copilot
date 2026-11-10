"""OpenAI 兼容适配器：DeepSeek / Qwen(dashscope兼容模式) / vLLM / Ollama 全走这一条实现。"""
import httpx

from ..config import settings
from .base import LLMResult


class OpenAICompatProvider:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model

    async def complete(self, prompt: str, *, system: str = "", max_tokens: int = 4096,
                       temperature: float = 0.7) -> LLMResult:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # 无密钥的自托管网关（如 Magpie）不发 Authorization——httpx 拒绝 b'Bearer ' 空值头
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={"model": self.model, "messages": messages,
                      "max_tokens": max_tokens, "temperature": temperature},
            )
            resp.raise_for_status()
            data = resp.json()
        usage = data.get("usage", {})
        return LLMResult(
            text=data["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
        )

"""按配置实例化 Provider。新增供应商：实现 LLMProvider 协议 + 在这里注册一行。"""
from ..config import settings
from .base import LLMProvider
from .fake import FakeProvider
from .openai_compat import OpenAICompatProvider


def get_provider() -> LLMProvider:
    if settings.llm_provider == "openai_compat":
        return OpenAICompatProvider()
    if settings.llm_provider == "fake":
        return FakeProvider()
    raise ValueError(f"未知 provider: {settings.llm_provider}（先实现再注册）")

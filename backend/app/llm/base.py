"""LLM Provider SPI：所有生成类能力（大纲/逐章/核查/文献摘要）都从这里走。

设计约束：
1. 换供应商 = 换配置，不改业务代码（原产品锁死一家是死穴）
2. 每次调用返回 token 用量——计费配额（billing 模块）依赖这个数字，不许凭空估算
3. prompt 全部放在 app/prompts/ 目录、纯文本、可审计——不许散在代码字符串里
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str


class LLMProvider(Protocol):
    async def complete(self, prompt: str, *, system: str = "", max_tokens: int = 4096,
                       temperature: float = 0.7) -> LLMResult: ...

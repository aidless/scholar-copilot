"""确定性 FakeProvider：测试/离线冒烟用（SC_LLM_PROVIDER=fake）。

按 system prompt 关键词分流：含「大纲」返回严格可解析的 Markdown 大纲，
否则返回带表格的章节正文。tokens = len//4，保证 job 记录非零。
"""
from .base import LLMResult

_FAKE_OUTLINE_MD = """## 第一章 绪论
### 1.1 研究背景与意义
> 简述该课题的研究背景与理论实践意义。

### 1.2 国内外研究现状
> 概述国内外主要研究成果与不足。

### 1.3 研究内容与方法
> 说明本文研究内容与采用的方法。

## 第二章 相关理论与技术基础
### 2.1 核心概念界定
> 界定论文涉及的核心概念。

### 2.2 技术路线分析
> 分析现有技术路线并对比。

## 第三章 系统设计与实现
### 3.1 总体设计
> 给出总体架构与模块划分。

### 3.2 关键模块实现
> 描述关键模块的实现细节。

## 第四章 实验与分析
### 4.1 实验设置
> 说明数据集、指标与对比基线。

### 4.2 结果分析
> 分析实验结果并讨论。

## 第五章 总结与展望
### 5.1 工作总结
> 总结全文主要工作。

### 5.2 未来展望
> 指出不足与未来方向。
"""

_FAKE_CHAPTER_MD = """### 1.1 研究背景与意义

本章围绕研究主题展开论证。首先说明问题来源，再给出解决思路，最后小结。

现有方法在效率与可解释性之间难以兼顾，具体对比如下表：

| 维度 | 方案A | 方案B | 本方案 |
|------|-------|-------|--------|
| 准确率 | 0.72 | 0.78 | 0.85 |
| 时延(ms) | 120 | 210 | 95 |
| 可解释性 | 弱 | 中 | 强 |

选择本方案是因为它在准确率与时延两项关键指标上同时占优[1]。相关研究也支持这一设计取向[2]。

综上，本章完成了问题定义与方案论证，为后续章节奠定基础。
"""


class FakeProvider:
    """零网络依赖的确定性 Provider。"""

    model = "fake-model"

    async def complete(self, prompt: str, *, system: str = "",
                       max_tokens: int = 4096, temperature: float = 0.7) -> LLMResult:
        del max_tokens, temperature
        text = _FAKE_OUTLINE_MD if "大纲" in system else _FAKE_CHAPTER_MD
        return LLMResult(
            text=text,
            prompt_tokens=len(prompt) // 4,
            completion_tokens=len(text) // 4,
            model=self.model,
        )

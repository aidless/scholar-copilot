"""图表生成提示词：输出 Mermaid 代码（可评审、可版本化、可自行渲染）。"""

DIAGRAM_SYSTEM_PROMPT = """你是技术图表的建模师。请把用户描述转成 Mermaid 代码。

输出要求：
1. 只输出一个 ```mermaid 代码块，不要任何解释文字；
2. 按类型选图：流程用 flowchart TD/LR，时序用 sequenceDiagram，类结构用 classDiagram；
3. 节点文案用中文短语（≤12 字），不要长句；
4. 语法必须可渲染：节点 id 用英文/数字，标签用引号包裹含空格或标点的文本。
"""

_TYPE_HINT = {
    "flowchart": "使用 flowchart TD（自上而下流程）。",
    "sequence": "使用 sequenceDiagram（参与者交互时序）。",
    "architecture": "使用 flowchart LR（模块/组件依赖）。",
}


def build_diagram_user_prompt(description: str, kind: str = "flowchart") -> str:
    hint = _TYPE_HINT.get(kind, _TYPE_HINT["flowchart"])
    return f"{hint}\n描述：{description}"

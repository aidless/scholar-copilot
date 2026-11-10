"""大纲 Markdown → 树结构解析器。

移植自 thesis_auto_generator/core/outline_generator.py::_parse_markdown_to_outline，
去掉 ORM 依赖，返回纯 dict（可直接存 order_outlines.tree_json）。

解析规则：
- ## 开头 → level 1（章节点）
- ### 开头 → level 2（节节点）
- #### 开头 → level 3（子节节点）
- > 引用 → 栈顶节点的 content 描述
- node_id: ch{n} / ch{n}_sec{m} / ch{n}_sec{m}_sub{k}
"""
import re
from typing import Dict, List


def parse_outline_markdown(md_text: str) -> Dict:
    """解析 Markdown 大纲文本为树结构。

    Raises:
        ValueError: 未找到任何章级标题（##）
    """
    root: Dict = {"id": "root", "title": "root", "level": 0, "content": "", "children": []}

    # 节点栈：stack[0]=root，栈顶是最近一个更深层级的节点
    stack: List[Dict] = [root]
    section_counters = [0, 0, 0]  # [章计数, 节计数, 子节计数]

    for raw_line in md_text.split("\n"):
        line = raw_line.strip()

        # 跳过空行和水平线
        if not line or re.match(r"^[-*_]{3,}$", line):
            continue

        heading_match = re.match(r"^(#{2,4})\s+(.+)$", line)
        if heading_match:
            hashes = heading_match.group(1)
            title = heading_match.group(2).strip()
            title = re.sub(r"[\*_]{1,3}", "", title)  # 去加粗/斜体标记
            level = len(hashes) - 1  # ## → 1, ### → 2, #### → 3

            if level == 1:
                section_counters[0] += 1
                node_id = f"ch{section_counters[0]}"
                section_counters[1] = 0
                section_counters[2] = 0
            elif level == 2:
                section_counters[1] += 1
                node_id = f"ch{section_counters[0]}_sec{section_counters[1]}"
                section_counters[2] = 0
            else:
                section_counters[2] += 1
                node_id = f"ch{section_counters[0]}_sec{section_counters[1]}_sub{section_counters[2]}"

            node: Dict = {"id": node_id, "title": title, "level": level, "content": "", "children": []}

            # 向上回溯栈，找到 level 比当前小的最近节点作为父节点
            while len(stack) > 1 and stack[-1]["level"] >= level:
                stack.pop()
            stack[-1]["children"].append(node)
            stack.append(node)
            continue

        desc_match = re.match(r"^>\s*(.+)$", line)
        if desc_match and len(stack) > 1:
            description = desc_match.group(1).strip()
            current = stack[-1]
            current["content"] = (current["content"] + "\n" + description).strip()

    if not root["children"]:
        raise ValueError("解析失败：未找到任何章级标题（##）")

    return root


def get_chapters(tree: Dict) -> List[Dict]:
    """取全部章级（level 1）节点。"""
    return tree.get("children", [])


def flat_list(tree: Dict) -> List[Dict]:
    """树的前序扁平化（含各级节点）。"""
    out: List[Dict] = []

    def walk(node: Dict) -> None:
        if node["level"] > 0:
            out.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(tree)
    return out

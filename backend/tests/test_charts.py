"""v1.9 #3：图表渲染（matplotlib → PNG）+ 插入 DOCX。"""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _spec(ctype="bar"):
    return {
        "type": ctype, "title": "各章字数",
        "labels": ["绪论", "综述", "方法"],
        "series": [{"name": "字数", "values": [1200, 3400, 2100]}],
        "xlabel": "章节", "ylabel": "字数",
    }


def test_render_bar_line_pie():
    from app.export.charts import render_chart
    for ctype in ("bar", "line", "pie"):
        png = render_chart(_spec(ctype))
        assert png.startswith(PNG_MAGIC)
        assert len(png) > 1000


def test_render_rejects_bad_type():
    from app.export.charts import render_chart
    with pytest.raises(ValueError):
        render_chart(_spec("scatter"))


def test_render_rejects_length_mismatch():
    from app.export.charts import render_chart
    bad = _spec()
    bad["series"][0]["values"] = [1, 2]  # labels 3 个
    with pytest.raises(ValueError):
        render_chart(bad)


def test_chart_endpoint_png():
    from app.main import create_app
    client = TestClient(create_app())
    r = client.post("/tools/chart", json=_spec("bar"))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(PNG_MAGIC)


def test_chart_endpoint_types_and_422():
    from app.main import create_app
    client = TestClient(create_app())
    r = client.get("/tools/chart/types")
    assert r.status_code == 200 and set(r.json()["types"]) == {"bar", "line", "pie"}
    bad = _spec("pie")
    bad["type"] = "nope"
    r = client.post("/tools/chart", json=bad)
    assert r.status_code == 422


def test_docx_embeds_chart():
    from app.export.docx_builder import build_thesis_docx
    chapters = [{"idx": 1, "node_id": "ch1", "title": "第一章 绪论",
                 "content_md": "正文内容。", "word_count": 6, "ai_level": "C"}]
    data = build_thesis_docx("测试论文", "本科", chapters, charts=[{"spec": _spec("bar"), "caption": "图1 各章字数"}])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert any(n.endswith(".png") for n in media), media

"""v1.8 #5：写作文体（writing_type）注册表与下单校验。

六种文体共用管线但大纲结构指引不同；下单时非法文体 422。
"""
from fastapi.testclient import TestClient

from app.prompts.outline_prompts import build_outline_user_prompt
from app.writing import genres

PHONE = "13800000011"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client):
    r = client.post("/auth/register",
                    json={"phone": PHONE, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_six_genres_defined():
    assert set(genres.GENRES) == {"thesis", "literature_review", "proposal",
                                  "journal_article", "task_book", "course_paper"}
    for key, spec in genres.GENRES.items():
        assert spec["label"] and spec["outline_hint"] and spec["writing_hint"]


def test_is_valid_and_helpers():
    assert genres.is_valid("thesis")
    assert not genres.is_valid("poster")
    assert genres.label_of("proposal") == "开题报告"
    assert "进度安排" in genres.outline_hint("proposal")
    # 未知类型回退默认
    assert genres.label_of("nope") == "毕业论文"


def test_outline_prompt_includes_genre_hint():
    base = build_outline_user_prompt("题", [], "计算机", 6000)
    assert "文体类型" not in base
    with_genre = build_outline_user_prompt(
        "题", [], "计算机", 6000, writing_type="literature_review",
        genre_label=genres.label_of("literature_review"),
        genre_hint=genres.outline_hint("literature_review"),
    )
    assert "文体类型" in with_genre and "文献综述" in with_genre
    assert "研究空白" in with_genre


def test_create_order_accepts_genre_and_rejects_unknown():
    client = make_client()
    token = register(client)
    r = client.post("/writing/orders",
                    json={"title": "文献综述订单", "education": "硕士",
                          "word_count": 8000, "writing_type": "literature_review"},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["writing_type"] == "literature_review"
    r = client.post("/writing/orders",
                    json={"title": "非法文体", "education": "硕士",
                          "word_count": 6000, "writing_type": "poster"},
                    headers=auth(token))
    assert r.status_code == 422


def test_create_order_default_thesis():
    client = make_client()
    token = register(client)
    r = client.post("/writing/orders",
                    json={"title": "默认文体", "education": "本科", "word_count": 6000},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["writing_type"] == "thesis"

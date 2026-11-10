"""v1.7：LaTeX 编译服务化（.tex → PDF via xelatex）。

本机无 TeX 发行版 → 真实编译用 skip；核心逻辑用 monkeypatch 验证：
①无引擎时抛 RuntimeError（路由转 502）；②引擎存在时成功产出 PDF 字节。
"""
from pathlib import Path

import pytest

from app.export import pdf as pdfmod


def test_no_engine_raises(monkeypatch):
    monkeypatch.setattr(pdfmod.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as ei:
        pdfmod.tex_bytes_to_pdf(b"\\documentclass{article}\\begin{document}x\\end{document}")
    # 必须是「未安装」这条分支，而不是「编译失败」——两者文案不同，避免弱断言
    assert "未安装 TeX" in str(ei.value)


def test_engine_success_writes_and_returns_pdf(monkeypatch, tmp_path):
    """模拟引擎：subprocess.run 时把 thesis.pdf 写进 cwd，函数应读回字节。"""
    monkeypatch.setattr(pdfmod.shutil, "which", lambda name: "/usr/bin/xelatex" if name == "xelatex" else None)

    class _FakeProc:
        returncode = 0
        stdout = b"ok"
        stderr = b""

    def _fake_run(cmd, cwd=None, capture_output=None, timeout=None, check=None):
        (Path(cwd) / "thesis.pdf").write_bytes(b"%PDF-1.5 faked")
        return _FakeProc()

    monkeypatch.setattr(pdfmod.subprocess, "run", _fake_run)
    out = pdfmod.tex_bytes_to_pdf(b"\\documentclass{article}")
    assert out.startswith(b"%PDF-1.5")


def test_engine_fail_no_pdf_raises(monkeypatch):
    monkeypatch.setattr(pdfmod.shutil, "which", lambda name: "/usr/bin/xelatex" if name == "xelatex" else None)

    class _FakeProc:
        returncode = 1
        stdout = b"! LaTeX Error: something wrong"
        stderr = b""

    monkeypatch.setattr(pdfmod.subprocess, "run",
                        lambda *a, **k: _FakeProc())
    with pytest.raises(RuntimeError) as ei:
        pdfmod.tex_bytes_to_pdf(b"\\bad")
    assert "LaTeX 编译失败" in str(ei.value)


def test_export_latexpdf_502_when_no_tex(monkeypatch):
    """端到端：完整订单导出 format=latexpdf，本机无 TeX → 502 且文案含 TeX。"""
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.export import pdf as _pdf
    monkeypatch.setattr(_pdf.shutil, "which", lambda name: None)

    pw = "Test123456"
    with TestClient(create_app()) as client:
        tok = client.post("/auth/register",
                          json={"phone": "13500001234", "password": pw,
                                "check_code": "000000"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        order = client.post("/writing/orders",
                            json={"title": "LaTeX 编译测试", "education": "本科", "word_count": 6000},
                            headers=h).json()
        client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=h)
        pay = client.post(f"/payments/orders/{order['id']}",
                          json={"pay_method": "wechat"}, headers=h).json()
        client.post(f"/payments/{pay['serial_no']}/confirm", headers=h)
        for node in ["ch1", "ch2", "ch3", "ch4", "ch5"]:
            r = client.post(f"/writing/orders/{order['id']}/chapters/{node}?wait=true",
                            json=None, headers=h)
            assert r.status_code == 200, r.text
        r = client.post(f"/writing/orders/{order['id']}/export?format=latexpdf", headers=h)
        assert r.status_code == 502, r.text
        assert "未安装 TeX" in r.json()["detail"]


@pytest.mark.skipif(not (pdfmod.shutil.which("xelatex") or pdfmod.shutil.which("lualatex")
                         or pdfmod.shutil.which("pdflatex")),
                    reason="本机无 TeX 发行版（CI 装 texlive 后执行真实编译）")
def test_tex_real_compile():
    from app.export.latex import build_thesis_tex
    tex = build_thesis_tex(title="真实编译测试", education="本科",
                           chapters=[{"title": "第一章 绪论", "word_count": 300,
                                      "ai_level": "A", "content_md": "这是正文内容。"}])
    out = pdfmod.tex_bytes_to_pdf(tex)
    assert out.startswith(b"%PDF")

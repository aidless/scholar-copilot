"""DOCX → PDF：用本机 LibreOffice headless 转换（沙箱内可用，无需云服务）。

设计取舍：不引第三方转换库（unoconv 等都要常驻进程），直接 subprocess 一次性转换；
失败时抛 RuntimeError，由路由转 502 并提示可用 docx 导出。
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

_SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")


def docx_bytes_to_pdf(docx_bytes: bytes, timeout: int = 180) -> bytes:
    if not _SOFFICE:
        raise RuntimeError("本机未安装 LibreOffice，无法导出 PDF；请改用 docx 导出")
    with tempfile.TemporaryDirectory(prefix="sc-pdf-") as tmp:
        src = Path(tmp) / "in.docx"
        src.write_bytes(docx_bytes)
        try:
            proc = subprocess.run(
                [_SOFFICE, "--headless", "--norestore", "--convert-to", "pdf",
                 "--outdir", tmp, str(src)],
                capture_output=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("PDF 转换超时（>180s），请改用 docx 导出") from exc
        out = Path(tmp) / "in.pdf"
        if not out.exists():
            detail = (proc.stderr or b"").decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"PDF 转换失败：{detail or '无输出文件'}")
        return out.read_bytes()


def tex_bytes_to_pdf(tex_bytes: bytes, timeout: int = 300) -> bytes:
    """LaTeX → PDF：用本机 xelatex 编译（中文需 ctex，故用 xelatex）。

    编译两遍以解析交叉引用（目录/编号），第二遍失败不影响产物；
    无 TeX 发行版时抛 RuntimeError，由路由转 502 并提示改用 tex/docx 导出。
    """
    engine = shutil.which("xelatex") or shutil.which("lualatex") or shutil.which("pdflatex")
    if not engine:
        raise RuntimeError("本机未安装 TeX 发行版（xelatex），无法编译 LaTeX；请改用 tex 或 docx 导出")
    with tempfile.TemporaryDirectory(prefix="sc-tex-") as tmp:
        src = Path(tmp) / "thesis.tex"
        src.write_bytes(tex_bytes)
        # 两遍编译：第一遍生成 .aux/.toc，第二遍定稿；用 -interaction=nonstopmode 防卡在交互
        last = None
        for _pass in range(2):
            try:
                last = subprocess.run(
                    [engine, "-interaction=nonstopmode", "-halt-on-error", "thesis.tex"],
                    cwd=tmp, capture_output=True, timeout=timeout, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"LaTeX 编译超时（>{timeout}s）") from exc
            if last.returncode != 0 and _pass == 0:
                out = Path(tmp) / "thesis.pdf"
                if not out.exists():
                    detail = (last.stdout or b"").decode("utf-8", "ignore")[-400:]
                    raise RuntimeError(f"LaTeX 编译失败：{detail.strip() or '无输出'}")
        out = Path(tmp) / "thesis.pdf"
        if not out.exists():
            detail = (last.stdout or b"").decode("utf-8", "ignore")[-400:] if last else ""
            raise RuntimeError(f"LaTeX 编译失败：{detail.strip() or '无 PDF 产物'}")
        return out.read_bytes()

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

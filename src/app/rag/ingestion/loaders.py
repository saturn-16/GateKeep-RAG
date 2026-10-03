from io import BytesIO
from pathlib import PurePath

from fastapi import UploadFile


ALLOWED_TYPES = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/markdown", "text/plain"}


def parse_document(filename: str, content_type: str | None, data: bytes) -> str:
    if content_type not in ALLOWED_TYPES:
        suffix = PurePath(filename).suffix.lower()
        if suffix not in {".pdf", ".docx", ".md", ".txt"}:
            raise ValueError("unsupported document type")
    suffix = PurePath(filename).suffix.lower()
    if content_type == "application/pdf" or suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages).strip()
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or suffix == ".docx":
        from docx import Document as DocxDocument

        return "\n".join(paragraph.text for paragraph in DocxDocument(BytesIO(data)).paragraphs).strip()
    return data.decode("utf-8").strip()


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("upload exceeds configured size limit")
    return data

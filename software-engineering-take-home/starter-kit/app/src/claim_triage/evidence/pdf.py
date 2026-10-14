"""PDF evidence.

The document is extracted once, up front, and passed in the opening message: it is evidence
the agent needs before it can plan, not something it should have to ask for (research D3).
An unreadable attachment is reported, never swallowed (US7 scenario 7).
"""
from __future__ import annotations

import io
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentText:
    status: str  # "ok" | "empty" | "unreadable"
    text: str = ""
    pages: int = 0

    @property
    def usable(self) -> bool:
        return self.status == "ok" and bool(self.text.strip())

    def note(self) -> str:
        if self.status == "unreadable":
            return "The attached document could not be read and was not used as evidence."
        if self.status == "empty":
            return "The attached document contained no extractable text."
        return ""


def extract(raw: bytes, limit: int = 8_000) -> DocumentText:
    if not raw:
        return DocumentText(status="unreadable")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        chunks = [(page.extract_text() or "") for page in reader.pages]
    except Exception:  # noqa: BLE001 - any parse failure is "unreadable" to the caller
        return DocumentText(status="unreadable")

    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
    if not text:
        return DocumentText(status="empty", pages=len(chunks))
    return DocumentText(status="ok", text=text[:limit], pages=len(chunks))

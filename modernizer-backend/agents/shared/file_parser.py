import io
import json
from pathlib import Path


def extract_text(filename: str, content: bytes) -> str:
    """Return plain text from an uploaded context file (PDF, DOCX, JSON, or text)."""
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            return "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()

        if ext in (".docx", ".doc"):
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

        if ext == ".json":
            data = json.loads(content.decode("utf-8", errors="replace"))
            return json.dumps(data, indent=2)

        return content.decode("utf-8", errors="replace")

    except Exception as exc:
        return f"[Could not extract text from {filename}: {exc}]"

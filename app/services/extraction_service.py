import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class ExtractionResult:
    raw_text: str
    page_count: int


class ExtractionService:
    def extract(self, file_path: str, content_type: str) -> ExtractionResult:
        """Extract raw text from a PDF or DOCX file."""
        if content_type == PDF_CONTENT_TYPE:
            return self._extract_pdf(file_path)
        elif content_type == DOCX_CONTENT_TYPE:
            return self._extract_docx(file_path)
        else:
            raise ValueError(f"Unsupported content type: {content_type!r}")

    def _extract_pdf(self, file_path: str) -> ExtractionResult:
        import pymupdf

        doc = pymupdf.open(file_path)
        pages = [page.get_text() for page in doc]
        doc.close()
        logger.info(f"Extracted {len(pages)} pages from PDF: {file_path}")
        return ExtractionResult(
            raw_text="\n\n".join(pages),
            page_count=len(pages),
        )

    def _extract_docx(self, file_path: str) -> ExtractionResult:
        from docx import Document

        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        logger.info(f"Extracted {len(paragraphs)} paragraphs from DOCX: {file_path}")
        return ExtractionResult(
            raw_text="\n\n".join(paragraphs),
            page_count=1,
        )

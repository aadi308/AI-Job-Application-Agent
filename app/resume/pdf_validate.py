from pypdf import PdfReader

from app.resume.models import PDFValidationReport

MAX_PAGES = 2


def validate_pdf(pdf_path: str, expected_email: str, expected_phone: str | None) -> PDFValidationReport:
    violations: list[str] = []
    reader = PdfReader(pdf_path)
    page_count = len(reader.pages)

    if page_count == 0:
        violations.append("PDF has zero pages")
    if page_count > MAX_PAGES:
        violations.append(f"PDF has {page_count} pages, exceeds max of {MAX_PAGES}")

    full_text = ""
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if not text.strip():
            violations.append(f"Page {i + 1} has no extractable text (possible empty/broken page)")
        full_text += text

    if expected_email and expected_email not in full_text:
        violations.append(f"Extracted text does not contain expected email {expected_email!r}")
    if expected_phone and expected_phone not in full_text:
        violations.append(f"Extracted text does not contain expected phone {expected_phone!r}")

    if "�" in full_text:
        violations.append("Extracted text contains broken/undecodable characters")

    return PDFValidationReport(
        passed=len(violations) == 0,
        page_count=page_count,
        violations=violations,
        extracted_text_length=len(full_text),
    )

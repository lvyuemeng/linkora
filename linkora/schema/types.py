"""
schema/types.py - Built-in document schema definitions.
"""

from typing import Any

from pydantic import Field

from linkora.schema.registry import DocumentFields, default_field_match


class PaperFields(DocumentFields):
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    cited_by_count: int = 0


class PaperSchema:
    doc_type: str = "paper"
    display_name: str = "Research Paper"
    fields_model: type[PaperFields] = PaperFields
    file_extensions: list[str] = [".pdf"]

    @staticmethod
    def extraction_prompt(raw_text: str, missing: list[str]) -> str:
        fields = ", ".join(missing)
        return (
            "You are extracting metadata from a research paper. "
            "Return JSON only, with keys exactly matching the requested fields.\n\n"
            f"Fields: {fields}\n"
            "Guidance: use null when missing; authors as array; year as integer.\n\n"
            "Paper excerpt:\n"
            f"{raw_text[:8000]}"
        )

    @staticmethod
    def filename_template(fields: PaperFields) -> str | None:
        if not fields.year or not fields.title:
            return None
        title_slug = fields.title.lower().replace(" ", "-")[:30]
        author_last = (
            fields.authors[0].split()[-1].lower() if fields.authors else "unknown"
        )
        return f"{fields.year}_{author_last}_{title_slug}"

    @staticmethod
    def field_match(key: str, candidate: Any, expected: str) -> bool:
        return default_field_match(key, candidate, expected)


class InvoiceFields(DocumentFields):
    vendor: str | None = None
    invoice_number: str | None = None
    date: str | None = None
    amount: float | None = None
    currency: str = "USD"
    line_items: list[dict] = Field(default_factory=list)


class InvoiceSchema:
    doc_type: str = "invoice"
    display_name: str = "Invoice"
    fields_model: type[InvoiceFields] = InvoiceFields
    file_extensions: list[str] = [".pdf", ".png", ".jpg", ".jpeg"]

    @staticmethod
    def extraction_prompt(raw_text: str, missing: list[str]) -> str:
        fields = ", ".join(missing)
        return (
            "You are extracting invoice fields. "
            "Return JSON only, with keys exactly matching the requested fields.\n\n"
            f"Fields: {fields}\n"
            "Guidance: amount as number, currency as 3-letter code, date as ISO if possible.\n\n"
            "Invoice excerpt:\n"
            f"{raw_text[:6000]}"
        )

    @staticmethod
    def filename_template(fields: InvoiceFields) -> str | None:
        if not fields.date or not fields.vendor:
            return None
        amount_str = f"{fields.amount:.2f}" if fields.amount else ""
        return f"{fields.date}_{fields.vendor}_{amount_str}"

    @staticmethod
    def field_match(key: str, candidate: Any, expected: str) -> bool:
        return default_field_match(key, candidate, expected)


class ManualFields(DocumentFields):
    product_name: str | None = None
    version: str | None = None
    manufacturer: str | None = None
    chapters: list[str] = Field(default_factory=list)


class ManualSchema:
    doc_type: str = "manual"
    display_name: str = "Manual"
    fields_model: type[ManualFields] = ManualFields
    file_extensions: list[str] = [".pdf"]

    @staticmethod
    def extraction_prompt(raw_text: str, missing: list[str]) -> str:
        fields = ", ".join(missing)
        return (
            "You are extracting product manual metadata. "
            "Return JSON only, with keys exactly matching the requested fields.\n\n"
            f"Fields: {fields}\n"
            "Guidance: product_name is the marketed product title; version may be model or revision.\n\n"
            "Manual excerpt:\n"
            f"{raw_text[:8000]}"
        )

    @staticmethod
    def filename_template(fields: ManualFields) -> str | None:
        if not fields.product_name:
            return None
        version_str = f"_v{fields.version}" if fields.version else ""
        return f"{fields.product_name}{version_str}_manual"

    @staticmethod
    def field_match(key: str, candidate: Any, expected: str) -> bool:
        return default_field_match(key, candidate, expected)


class ContractFields(DocumentFields):
    parties: list[str] = Field(default_factory=list)
    effective_date: str | None = None
    expiry_date: str | None = None
    value: float | None = None
    currency: str = "USD"


class ContractSchema:
    doc_type: str = "contract"
    display_name: str = "Contract"
    fields_model: type[ContractFields] = ContractFields
    file_extensions: list[str] = [".pdf"]

    @staticmethod
    def extraction_prompt(raw_text: str, missing: list[str]) -> str:
        fields = ", ".join(missing)
        return (
            "You are extracting contract metadata. "
            "Return JSON only, with keys exactly matching the requested fields.\n\n"
            f"Fields: {fields}\n"
            "Guidance: parties as array; dates as ISO if possible; value as number.\n\n"
            "Contract excerpt:\n"
            f"{raw_text[:8000]}"
        )

    @staticmethod
    def filename_template(fields: ContractFields) -> str | None:
        if not fields.effective_date or not fields.parties:
            return None
        parties_str = "_".join(p.split()[-1] for p in fields.parties[:2])
        return f"contract_{fields.effective_date}_{parties_str}"

    @staticmethod
    def field_match(key: str, candidate: Any, expected: str) -> bool:
        return default_field_match(key, candidate, expected)


class GenericFields(DocumentFields):
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class GenericSchema:
    doc_type: str = "generic"
    display_name: str = "Generic Document"
    fields_model: type[GenericFields] = GenericFields
    file_extensions: list[str] = [".pdf", ".txt", ".md", ".doc", ".docx"]

    @staticmethod
    def extraction_prompt(raw_text: str, missing: list[str]) -> str:
        fields = ", ".join(missing)
        return (
            "You are extracting generic document metadata. "
            "Return JSON only, with keys exactly matching the requested fields.\n\n"
            f"Fields: {fields}\n"
            "Guidance: tags as array of short keywords; category as short noun phrase.\n\n"
            "Document excerpt:\n"
            f"{raw_text[:6000]}"
        )

    @staticmethod
    def filename_template(fields: GenericFields) -> str | None:
        if not fields.title:
            return None
        title_slug = fields.title.lower().replace(" ", "-")[:40]
        return f"doc_{title_slug}"

    @staticmethod
    def field_match(key: str, candidate: Any, expected: str) -> bool:
        return default_field_match(key, candidate, expected)


__all__ = [
    "PaperFields",
    "PaperSchema",
    "InvoiceFields",
    "InvoiceSchema",
    "ManualFields",
    "ManualSchema",
    "ContractFields",
    "ContractSchema",
    "GenericFields",
    "GenericSchema",
]

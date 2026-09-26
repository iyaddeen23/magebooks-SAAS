"""Invoice PDF Service Orchestration.

Manages compilation of air-gapped PDFs, multi-tenant Cloudflare R2 key partitioning,
and presigned download URL generation.
"""

from apps.core.services.storage import BaseStorageService, get_storage_service
from apps.invoicing.models import Invoice
from apps.invoicing.services.pdf_compiler import AirGappedPDFCompiler


class InvoicePDFService:
    """Orchestrates invoice PDF generation, R2 uploads, and presigned download links."""

    @classmethod
    def get_storage_key(cls, invoice: Invoice) -> str:
        """Computes hierarchical tenant-partitioned R2 storage key.

        Format: {tenant_id}/invoices/{YYYY}/{MM}/{invoice_id}.pdf
        """
        year = invoice.issue_date.year
        month = f"{invoice.issue_date.month:02d}"
        return f"{invoice.organization_id}/invoices/{year}/{month}/{invoice.id}.pdf"

    @classmethod
    def generate_and_upload_invoice_pdf(
        cls,
        invoice: Invoice,
        storage_service: BaseStorageService | None = None,
    ) -> tuple[str, str]:
        """Compiles the invoice PDF, uploads to Cloudflare R2 / MockR2, and updates invoice record.

        Returns:
            tuple[str, str]: (presigned_download_url, storage_key)
        """
        storage = storage_service or get_storage_service()
        storage_key = cls.get_storage_key(invoice)

        # 1. Compile air-gapped PDF in-memory
        pdf_bytes = AirGappedPDFCompiler.compile_invoice_pdf(invoice)

        # 2. Upload to storage
        storage.upload_file_bytes(
            key=storage_key,
            data=pdf_bytes,
            content_type="application/pdf",
        )

        # 3. Generate 15-minute presigned download URL
        presigned_url = storage.generate_presigned_download_url(storage_key, expires_in=900)

        # 4. Update invoice record with the storage key reference
        invoice.pdf_url = storage_key
        invoice.save(update_fields=["pdf_url", "updated_at"])

        return presigned_url, storage_key

    @classmethod
    def get_invoice_pdf_download_url(
        cls,
        invoice: Invoice,
        expires_in: int = 900,
        storage_service: BaseStorageService | None = None,
    ) -> str:
        """Retrieves or generates a presigned download URL for the invoice PDF."""
        storage = storage_service or get_storage_service()
        storage_key = invoice.pdf_url

        if not storage_key or not storage.file_exists(storage_key):
            presigned_url, _ = cls.generate_and_upload_invoice_pdf(invoice, storage_service=storage)
            return presigned_url

        return storage.generate_presigned_download_url(storage_key, expires_in=expires_in)

    @classmethod
    def get_invoice_pdf_raw_bytes(
        cls,
        invoice: Invoice,
        storage_service: BaseStorageService | None = None,
    ) -> bytes:
        """Retrieves raw binary PDF bytes from storage, generating if not already cached."""
        storage = storage_service or get_storage_service()
        storage_key = invoice.pdf_url

        if storage_key and storage.file_exists(storage_key):
            return storage.get_file_bytes(storage_key)

        _, new_key = cls.generate_and_upload_invoice_pdf(invoice, storage_service=storage)
        return storage.get_file_bytes(new_key)

"""Asynchronous GRA E-VAT Clearance Dispatcher.

Handles queuing invoice clearance tasks to asynchronous workers.
In Sprint 3, provides an abstract dispatch interface.
In Sprint 4 (Feature 4.4), transparently routes to Celery's clear_with_gra.delay().
"""

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def enqueue_gra_clearance(invoice_id: uuid.UUID | str) -> dict[str, Any]:
    """Enqueues an invoice for asynchronous GRA E-VAT clearance.

    Returns task metadata dictionary.
    """
    invoice_uuid_str = str(invoice_id)
    logger.info("Enqueuing invoice %s for asynchronous GRA E-VAT clearance", invoice_uuid_str)

    # In Sprint 4, this hooks into Celery:
    # from apps.tax.tasks import clear_with_gra
    # task = clear_with_gra.delay(invoice_uuid_str)
    # return {"task_id": task.id, "status": "QUEUED", "invoice_id": invoice_uuid_str}

    return {
        "task_id": f"mock-task-{invoice_uuid_str[:8]}",
        "status": "QUEUED",
        "invoice_id": invoice_uuid_str,
    }

"""Background tasks. Each is a placeholder pointing at the task that fills it in."""

from __future__ import annotations

import logging

from nexus.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="nexus.ingestion.process_document", bind=True, max_retries=3)
def process_document(self, document_version_id: str) -> dict[str, object]:  # noqa: ANN001
    """TODO(KB-002): parse, chunk, embed and index a document version.

    Must be idempotent by (document_version_id, chunking_strategy): a re-run
    replaces the chunk set in one transaction rather than duplicating it.
    """
    logger.info("ingestion requested for %s", document_version_id)
    return {"status": "not_implemented", "document_version_id": document_version_id}


@celery_app.task(name="nexus.rollups.compute_hourly")
def compute_hourly_rollups(period_start: str | None = None) -> dict[str, object]:
    """TODO(OBS-004): aggregate into metric_rollups.

    Idempotent by (period, grain, dimension_hash). Percentiles come from merged
    t-digest sketches — averaging stored percentiles across buckets produces a
    plausible number that is simply wrong.
    """
    logger.info("rollup requested for %s", period_start)
    return {"status": "not_implemented"}


@celery_app.task(name="nexus.evaluation.run", bind=True)
def run_evaluation(self, eval_run_id: str) -> dict[str, object]:  # noqa: ANN001
    """TODO(EVAL-004): execute a dataset against a pinned configuration and log
    the result to MLflow. Cancellation must preserve completed items."""
    logger.info("evaluation requested for %s", eval_run_id)
    return {"status": "not_implemented", "eval_run_id": eval_run_id}

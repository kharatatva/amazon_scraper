"""Offline tests for pipeline preflight behavior."""

import unittest
from unittest.mock import AsyncMock, patch

from scripts import run_full_pipeline


class PipelinePreflightPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_failure_is_persisted_to_the_created_run(self):
        with patch.object(run_full_pipeline, "configure_logging"), \
             patch.object(run_full_pipeline, "normalize_pipeline_input",
                          return_value=("beauty", "skin-care", 5)), \
             patch.object(run_full_pipeline, "create_search_run_for_pipeline", return_value=73) as create_run, \
             patch.object(run_full_pipeline, "_run_pipeline",
                          new_callable=AsyncMock, side_effect=RuntimeError("proxy acquisition failed")), \
             patch.object(run_full_pipeline, "log_scrape_error") as log_error, \
             patch.object(run_full_pipeline, "update_search_run") as update_run, \
             patch.object(run_full_pipeline.logger, "exception"):
            with self.assertRaisesRegex(RuntimeError, "proxy acquisition failed"):
                await run_full_pipeline.run_pipeline("Beauty", "Skin Care", 5)

        create_run.assert_called_once_with("beauty", "skin-care")
        log_error.assert_called_once_with(
            search_run_id=73,
            url="PIPELINE",
            error_type="RuntimeError",
            error_message="proxy acquisition failed",
        )
        update_run.assert_called_once_with(
            search_run_id=73,
            status="failed",
            current_stage=run_full_pipeline.STAGE_FAILED,
            current_task="Pipeline failed",
            notes="proxy acquisition failed",
        )


if __name__ == "__main__":
    unittest.main()

"""Process boundary for cancellable AI synchronization inference."""
from __future__ import annotations

import os


def run_ai_sync_process(config: dict, messages) -> None:
    """Run the Qt worker in a child process and forward its signals."""
    os.environ["_PYLRCGET_AI_SYNC_CHILD"] = "1"
    from .ai_sync_worker import AiSyncWorker

    worker = AiSyncWorker(**config)
    worker.progress.connect(lambda message: messages.put(("progress", message)))
    worker.completed.connect(
        lambda ok, message, output: messages.put(
            ("completed", bool(ok), str(message), str(output))
        )
    )
    worker.run()


__all__ = ["run_ai_sync_process"]

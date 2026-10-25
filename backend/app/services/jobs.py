"""Background job execution.

``JobRunner`` is the seam for a real queue: a Celery/RQ runner would implement
``submit`` by enqueueing the job ID, with a worker calling the same
``DocumentProcessor.run(job_id)``. Jobs take only IDs, never ORM objects or sessions.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable

from fastapi import BackgroundTasks

JobFunc = Callable[[uuid.UUID], None]


class JobRunner(ABC):
    @abstractmethod
    def submit(self, func: JobFunc, job_id: uuid.UUID) -> None: ...


class BackgroundTaskRunner(JobRunner):
    """Runs the job in-process after the HTTP response is sent (FastAPI BackgroundTasks).

    Limitation: jobs are lost if the process stops; stale-job detection lets them be retried.
    """

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self._tasks = background_tasks

    def submit(self, func: JobFunc, job_id: uuid.UUID) -> None:
        self._tasks.add_task(func, job_id)


class InlineJobRunner(JobRunner):
    """Runs the job immediately in the caller's thread (scripts, debugging)."""

    def submit(self, func: JobFunc, job_id: uuid.UUID) -> None:
        func(job_id)

"""Bounded ThreadPoolExecutor for Telegram lookup jobs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
import logging
from threading import BoundedSemaphore, Lock, local
from typing import Callable, Protocol

from app.models import TelegramUpdateRepository, TelegramUpdateState
from app.services.errors import ErrorCode, VrServiceError


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LookupJob:
    update_id: int
    telegram_user_id: int
    database_user_id: int
    chat_id: int
    input_plate: str


class EnqueueResult(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    BUSY = "BUSY"


class JobHandler(Protocol):
    def __call__(self, job: LookupJob) -> None: ...


class WorkerService:
    def __init__(
        self,
        handler_factory: Callable[[int], JobHandler],
        updates: TelegramUpdateRepository,
        *,
        max_workers: int = 2,
        queue_size: int = 20,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than zero")
        if queue_size <= 0:
            raise ValueError("queue_size must be greater than zero")
        self.max_workers = max_workers
        self.queue_size = queue_size
        self._handler_factory = handler_factory
        self._updates = updates
        self._capacity = BoundedSemaphore(queue_size)
        self._thread_local = local()
        self._worker_index = 0
        self._index_lock = Lock()
        self._closed = False
        self._close_lock = Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="dktle-worker",
            initializer=self._initialize_worker,
        )

    @property
    def pending_count(self) -> int:
        # CPython's semaphore exposes no public count; this value is diagnostic
        # only and never participates in correctness.
        return self.queue_size - int(getattr(self._capacity, "_value", 0))

    def submit(self, job: LookupJob) -> EnqueueResult:
        with self._close_lock:
            if self._closed:
                return EnqueueResult.BUSY
            if not self._capacity.acquire(blocking=False):
                return EnqueueResult.BUSY
            if not self._updates.reserve(
                job.update_id,
                job.telegram_user_id,
                job.chat_id,
            ):
                self._capacity.release()
                return EnqueueResult.DUPLICATE
            try:
                self._executor.submit(self._run_job, job)
            except RuntimeError:
                self._updates.release(job.update_id)
                self._capacity.release()
                return EnqueueResult.BUSY
        return EnqueueResult.ACCEPTED

    def close(self, *, wait: bool = True) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _initialize_worker(self) -> None:
        with self._index_lock:
            worker_index = self._worker_index
            self._worker_index += 1
        self._thread_local.handler = self._handler_factory(worker_index)

    def _run_job(self, job: LookupJob) -> None:
        state = TelegramUpdateState.COMPLETED
        error_code: str | None = None
        try:
            handler: JobHandler = self._thread_local.handler
            handler(job)
        except VrServiceError as exc:
            state = TelegramUpdateState.FAILED
            error_code = exc.code.value
            LOGGER.warning("Telegram lookup job failed with code=%s", error_code)
        except Exception:
            state = TelegramUpdateState.FAILED
            error_code = ErrorCode.SOURCE_ERROR.value
            LOGGER.exception("Telegram lookup worker failed unexpectedly")
        finally:
            try:
                self._updates.finish(job.update_id, state, error_code=error_code)
            finally:
                self._capacity.release()

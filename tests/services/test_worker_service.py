from threading import Barrier, Event, Lock

from app.database import Database
from app.models import TelegramUpdateRepository, TelegramUpdateState
from app.services.worker_service import EnqueueResult, LookupJob, WorkerService


def job(update_id: int, chat_id: int | None = None) -> LookupJob:
    return LookupJob(update_id, 1000 + update_id, 1, chat_id or update_id, "00A00000T")


def repository(tmp_path) -> TelegramUpdateRepository:
    database = Database(tmp_path / "workers.sqlite3")
    database.initialize()
    return TelegramUpdateRepository(database)


def test_two_workers_use_distinct_handlers_and_keep_chat_mapping(tmp_path) -> None:
    updates = repository(tmp_path)
    barrier = Barrier(2)
    lock = Lock()
    deliveries: list[tuple[int, int, int]] = []

    def factory(worker_index):
        def handler(item):
            barrier.wait(timeout=2)
            with lock:
                deliveries.append((worker_index, item.update_id, item.chat_id))

        return handler

    workers = WorkerService(factory, updates, max_workers=2, queue_size=2)
    assert workers.submit(job(1, 101)) is EnqueueResult.ACCEPTED
    assert workers.submit(job(2, 202)) is EnqueueResult.ACCEPTED
    workers.close()

    assert {item[0] for item in deliveries} == {0, 1}
    assert {(item[1], item[2]) for item in deliveries} == {(1, 101), (2, 202)}


def test_duplicate_update_is_processed_once(tmp_path) -> None:
    updates = repository(tmp_path)
    release = Event()
    started = Event()
    calls: list[int] = []

    def factory(_):
        def handler(item):
            calls.append(item.update_id)
            started.set()
            release.wait(timeout=2)

        return handler

    workers = WorkerService(factory, updates, max_workers=1, queue_size=2)
    assert workers.submit(job(10)) is EnqueueResult.ACCEPTED
    assert started.wait(timeout=2)
    assert workers.submit(job(10)) is EnqueueResult.DUPLICATE
    release.set()
    workers.close()

    assert calls == [10]
    assert updates.get(10).state is TelegramUpdateState.COMPLETED


def test_full_queue_returns_busy_without_reserving_update(tmp_path) -> None:
    updates = repository(tmp_path)
    release = Event()

    def factory(_):
        return lambda item: release.wait(timeout=2)

    workers = WorkerService(factory, updates, max_workers=1, queue_size=1)
    assert workers.submit(job(20)) is EnqueueResult.ACCEPTED
    assert workers.submit(job(21)) is EnqueueResult.BUSY
    assert updates.get(21) is None
    release.set()
    workers.close()


def test_worker_failure_does_not_stop_next_job(tmp_path) -> None:
    updates = repository(tmp_path)

    def factory(_):
        def handler(item):
            if item.update_id == 30:
                raise ValueError("synthetic worker failure")

        return handler

    workers = WorkerService(factory, updates, max_workers=1, queue_size=2)
    assert workers.submit(job(30)) is EnqueueResult.ACCEPTED
    assert workers.submit(job(31)) is EnqueueResult.ACCEPTED
    workers.close()

    assert updates.get(30).state is TelegramUpdateState.FAILED
    assert updates.get(31).state is TelegramUpdateState.COMPLETED

from datetime import date

import pytest

from app.database import Database
from app.models import LookupRepository
from app.services.errors import AuthenticationError, CaptchaInvalidError, SessionExpiredError
from app.services.captcha_onnx import CaptchaModelError, CaptchaPrediction
from app.services.source_pool import SourcePool, UserSourcePool
from app.services.vr_parser import VehicleResult
from app.services.webforms_client import CaptchaChallenge
from app.services.worker_service import LookupJob
from app.views.telegram_view import TelegramView


VEHICLE = VehicleResult("Ô tô con", "NHÃN HIỆU", date(2030, 1, 2))


class FakeSourceClient:
    def __init__(self, *, lookup_outcome=VEHICLE, captcha_outcomes=None) -> None:
        self.authenticated = False
        self.lookup_outcome = lookup_outcome
        self.captcha_outcomes = list(captcha_outcomes or [None])
        self.refresh_count = 0
        self.lookup_plates = []
        self.closed = False

    def start_login(self):
        return CaptchaChallenge("https://source.test/captcha.jpg")

    def refresh_captcha(self):
        self.refresh_count += 1
        return CaptchaChallenge(f"https://source.test/captcha-{self.refresh_count}.jpg")

    def download_captcha(self, challenge):
        return f"image-{self.refresh_count}".encode()

    def current_captcha_challenge(self):
        return CaptchaChallenge(f"https://source.test/captcha-{self.refresh_count}.jpg")

    def submit_login(self, value):
        outcome = self.captcha_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.authenticated = True

    def lookup_candidate(self, plate):
        self.lookup_plates.append(plate)
        if isinstance(self.lookup_outcome, BaseException):
            raise self.lookup_outcome
        return self.lookup_outcome

    def close(self):
        self.closed = True


def make_pool(tmp_path, clients, messages):
    database = Database(tmp_path / "source-pool.sqlite3")
    database.initialize([1001, 1002])
    return SourcePool(
        clients,
        LookupRepository(database),
        lambda chat_id, text: messages.append((chat_id, text)),
        TelegramView(),
        candidate_delay_seconds=0,
    )


class FakeRecognizer:
    def __init__(self, predictions):
        self.predictions = list(predictions)
        self.images = []

    def predict(self, image):
        self.images.append(image)
        outcome = self.predictions.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_manual_login_authenticates_each_worker_sequentially(tmp_path) -> None:
    clients = [FakeSourceClient(), FakeSourceClient()]
    pool = make_pool(tmp_path, clients, [])

    first = pool.start_login()
    second = pool.submit_captcha("GOOD1")
    ready = pool.submit_captcha("GOOD2")

    assert first.prompt.worker_number == 1
    assert second.prompt.worker_number == 2
    assert ready.ready is True
    assert pool.ready is True
    assert pool.authenticated_workers == 2


def test_bad_captcha_refreshes_without_advancing_worker(tmp_path) -> None:
    client = FakeSourceClient(captcha_outcomes=[CaptchaInvalidError(), None])
    pool = make_pool(tmp_path, [client], [])
    pool.start_login()

    retry = pool.submit_captcha("BAD")
    ready = pool.submit_captcha("GOOD")

    assert retry.prompt.worker_number == 1
    assert retry.prompt.attempt == 2
    assert client.refresh_count == 1
    assert ready.ready is True


def test_worker_handler_uses_its_own_client_and_database_user(tmp_path) -> None:
    messages = []
    clients = [FakeSourceClient(), FakeSourceClient()]
    for client in clients:
        client.authenticated = True
    pool = make_pool(tmp_path, clients, messages)
    first_handler = pool.handler_factory(0)
    second_handler = pool.handler_factory(1)

    first_handler(LookupJob(1, 1001, 1, 5001, "00A00000T"))
    second_handler(LookupJob(2, 1002, 2, 5002, "00A00000V"))

    assert clients[0].lookup_plates == ["00A00000T"]
    assert clients[1].lookup_plates == ["00A00000V"]
    assert [item[0] for item in messages] == [5001, 5002]
    assert "Ô tô con" in messages[0][1]


def test_session_expiry_marks_only_affected_worker_not_ready(tmp_path) -> None:
    messages = []
    clients = [FakeSourceClient(lookup_outcome=SessionExpiredError()), FakeSourceClient()]
    for client in clients:
        client.authenticated = True
    pool = make_pool(tmp_path, clients, messages)

    with pytest.raises(SessionExpiredError):
        pool.handler_factory(0)(LookupJob(1, 1001, 1, 5001, "00A00000T"))

    assert clients[0].authenticated is False
    assert clients[1].authenticated is True
    assert pool.ready is False
    assert messages[-1][1] == TelegramView.source_not_ready()


def test_manual_mode_never_calls_recognizer(tmp_path) -> None:
    client = FakeSourceClient()
    recognizer = FakeRecognizer([CaptchaPrediction("AUTO", 1.0)])
    pool = make_pool(tmp_path, [client], [])
    pool.recognizer = recognizer

    response = pool.start_login()

    assert response.prompt is not None
    assert recognizer.images == []
    assert client.authenticated is False


def test_auto_low_confidence_refreshes_and_retries_until_login(tmp_path) -> None:
    client = FakeSourceClient()
    recognizer = FakeRecognizer(
        [CaptchaPrediction("LOW1", 0.4), CaptchaPrediction("GOOD", 0.99)]
    )
    database = Database(tmp_path / "auto-low.sqlite3")
    database.initialize([1001])
    pool = SourcePool(
        [client],
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        captcha_mode="auto",
        recognizer=recognizer,
        confidence_threshold=0.9,
    )

    response = pool.start_login()

    assert response.ready is True
    assert client.authenticated is True
    assert client.refresh_count == 1
    assert recognizer.images == [b"image-0", b"image-1"]


def test_auto_high_confidence_authenticates_all_workers(tmp_path) -> None:
    clients = [FakeSourceClient(), FakeSourceClient()]
    recognizer = FakeRecognizer(
        [CaptchaPrediction("GOOD1", 0.99), CaptchaPrediction("GOOD2", 0.98)]
    )
    database = Database(tmp_path / "auto-ready.sqlite3")
    database.initialize([1001])
    pool = SourcePool(
        clients,
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        captcha_mode="auto",
        recognizer=recognizer,
    )

    response = pool.start_login()

    assert response.ready is True
    assert pool.ready is True
    assert len(recognizer.images) == 2


def test_wrong_auto_prediction_solves_next_challenge_until_login(tmp_path) -> None:
    client = FakeSourceClient(captcha_outcomes=[CaptchaInvalidError(), None])
    recognizer = FakeRecognizer(
        [CaptchaPrediction("WRONG", 0.99), CaptchaPrediction("RIGHT", 0.99)]
    )
    database = Database(tmp_path / "auto-wrong.sqlite3")
    database.initialize([1001])
    pool = SourcePool(
        [client],
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        captcha_mode="auto",
        recognizer=recognizer,
    )

    ready = pool.start_login()

    assert ready.ready is True
    assert client.authenticated is True
    assert len(recognizer.images) == 2


def test_auto_captcha_attempt_limit_does_not_stop_retry_loop(tmp_path) -> None:
    failures = [CaptchaInvalidError() for _ in range(4)]
    client = FakeSourceClient(captcha_outcomes=[*failures, None])
    recognizer = FakeRecognizer(
        [CaptchaPrediction(f"TRY{i}", 0.99) for i in range(5)]
    )
    database = Database(tmp_path / "auto-unbounded.sqlite3")
    database.initialize([1001])
    pool = SourcePool(
        [client],
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        max_captcha_attempts=1,
        captcha_mode="auto",
        recognizer=recognizer,
    )

    response = pool.start_login()

    assert response.ready is True
    assert client.authenticated is True
    assert len(recognizer.images) == 5


def test_auto_model_failure_falls_back_to_manual_without_refresh(tmp_path) -> None:
    client = FakeSourceClient()
    recognizer = FakeRecognizer([CaptchaModelError("synthetic")])
    database = Database(tmp_path / "auto-model-error.sqlite3")
    database.initialize([1001])
    pool = SourcePool(
        [client],
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        captcha_mode="auto",
        recognizer=recognizer,
    )

    response = pool.start_login()

    assert response.prompt is not None
    assert response.prompt.image == b"image-0"
    assert response.prompt.attempt == 1
    assert "nhập tay" in response.message
    assert client.refresh_count == 0


def test_auto_does_not_retry_authentication_failure(tmp_path) -> None:
    client = FakeSourceClient(captcha_outcomes=[AuthenticationError("bad credentials")])
    recognizer = FakeRecognizer([CaptchaPrediction("GOOD", 0.99)])
    database = Database(tmp_path / "auto-auth-error.sqlite3")
    database.initialize([1001])
    pool = SourcePool(
        [client],
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        captcha_mode="auto",
        recognizer=recognizer,
    )

    with pytest.raises(AuthenticationError, match="bad credentials"):
        pool.start_login()

    assert len(recognizer.images) == 1
    assert client.refresh_count == 0


def test_per_user_pool_isolates_accounts_sessions_and_logout(tmp_path) -> None:
    database = Database(tmp_path / "per-user.sqlite3")
    database.initialize([1001, 1002])
    created = []

    def client_factory(username, password):
        client = FakeSourceClient()
        client.source_username = username
        client.source_password = password
        created.append(client)
        return client

    recognizer = FakeRecognizer(
        [CaptchaPrediction("GOOD", 0.99), CaptchaPrediction("GOOD", 0.99)]
    )
    messages = []
    pool = UserSourcePool(
        client_factory,
        LookupRepository(database),
        lambda chat_id, text: messages.append((chat_id, text)),
        TelegramView(),
        candidate_delay_seconds=0,
        recognizer=recognizer,
    )

    assert pool.login(1001, "account-one", "password-one").ready is True
    assert pool.login(1002, "account-two", "password-two").ready is True
    pool.handler_factory(0)(LookupJob(1, 1001, 1, 5001, "00A00000T"))
    pool.handler_factory(1)(LookupJob(2, 1002, 2, 5002, "00A00000V"))

    assert len(created) == 2
    assert created[0] is not created[1]
    assert created[0].source_username == "account-one"
    assert created[1].source_username == "account-two"
    assert created[0].lookup_plates == ["00A00000T"]
    assert created[1].lookup_plates == ["00A00000V"]
    assert pool.authenticated_users == 2
    assert pool.logout(1001) is True
    assert created[0].closed is True
    assert pool.ready_for(1001) is False
    assert pool.ready_for(1002) is True


def test_per_user_session_expiry_does_not_logout_other_user(tmp_path) -> None:
    database = Database(tmp_path / "per-user-expiry.sqlite3")
    database.initialize([1001, 1002])
    clients = [
        FakeSourceClient(lookup_outcome=SessionExpiredError()),
        FakeSourceClient(),
    ]
    pool = UserSourcePool(
        lambda _username, _password: clients.pop(0),
        LookupRepository(database),
        lambda *_: None,
        TelegramView(),
        candidate_delay_seconds=0,
        recognizer=FakeRecognizer(
            [CaptchaPrediction("GOOD", 0.99), CaptchaPrediction("GOOD", 0.99)]
        ),
    )
    pool.login(1001, "one", "one-pass")
    pool.login(1002, "two", "two-pass")

    with pytest.raises(SessionExpiredError):
        pool.handler_factory(0)(LookupJob(1, 1001, 1, 5001, "00A00000T"))

    assert pool.ready_for(1001) is False
    assert pool.ready_for(1002) is True

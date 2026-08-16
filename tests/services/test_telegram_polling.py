from app.services.telegram_polling import TelegramPollingService


class FakeBot:
    def __init__(self, batches):
        self.batches = list(batches)
        self.offsets = []

    def get_updates(self, *, offset, timeout):
        self.offsets.append((offset, timeout))
        return self.batches.pop(0)


class FakeController:
    def __init__(self, fail_id=None):
        self.fail_id = fail_id
        self.handled = []

    def handle_update(self, update):
        self.handled.append(update["update_id"])
        if update["update_id"] == self.fail_id:
            raise RuntimeError("synthetic")


def test_polling_advances_offset_after_every_valid_update() -> None:
    bot = FakeBot([[{"update_id": 10}, {"update_id": 11}]])
    controller = FakeController()
    polling = TelegramPollingService(bot, controller, poll_timeout_seconds=20)

    assert polling.run_once() == 2
    assert controller.handled == [10, 11]
    assert polling.offset == 12
    assert bot.offsets == [(None, 20)]


def test_handler_failure_does_not_replay_or_drop_following_update() -> None:
    bot = FakeBot([[{"update_id": 20}, {"update_id": 21}]])
    controller = FakeController(fail_id=20)
    polling = TelegramPollingService(bot, controller)

    assert polling.run_once() == 2
    assert controller.handled == [20, 21]
    assert polling.offset == 22

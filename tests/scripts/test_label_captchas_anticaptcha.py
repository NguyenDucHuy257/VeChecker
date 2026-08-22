from scripts.label_captchas_anticaptcha import (
    NO_SLOT_ERROR,
    solve_with_retry,
    unlabelled_images,
    valid_label,
)


def test_unlabelled_images_selects_jpegs_whose_stem_is_not_four_chars(tmp_path):
    for name in ("10000.jpg", "123.jpeg", "AB12.jpg", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")

    assert [path.name for path in unlabelled_images(tmp_path)] == [
        "10000.jpg",
        "123.jpeg",
    ]


def test_valid_label_requires_four_ascii_alphanumeric_chars():
    assert valid_label("aB09")
    assert not valid_label("ABC")
    assert not valid_label("ABCDE")
    assert not valid_label("AB-1")
    assert not valid_label("áB12")


def test_solve_retries_immediately_when_no_worker_slot_is_available(tmp_path):
    class Solver:
        def __init__(self):
            self.answers = [0, 0, "aB09"]
            self.error_code = ""

        def solve_and_return_solution(self, _path):
            answer = self.answers.pop(0)
            self.error_code = NO_SLOT_ERROR if answer == 0 else ""
            return answer

    answer, retries = solve_with_retry(Solver(), tmp_path / "10000.jpg")

    assert answer == "aB09"
    assert retries == 2


def test_solve_does_not_retry_a_permanent_error(tmp_path):
    class Solver:
        error_code = "ERROR_ZERO_BALANCE"

        def solve_and_return_solution(self, _path):
            return 0

    answer, retries = solve_with_retry(Solver(), tmp_path / "10000.jpg")

    assert answer == 0
    assert retries == 0

from app.main import create_application
from app.models import UserRepository, UserRole, UserStatus
from app.views.script_view import ScriptView


def test_application_factory_migrates_database_and_seeds_admin(tmp_path) -> None:
    database_path = tmp_path / "runtime" / "test.sqlite3"
    captcha_dir = tmp_path / "runtime" / "captcha"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VR_USERNAME=synthetic-user\n"
        "VR_PASSWORD=synthetic-password\n"
        "TELEGRAM_ADMIN_IDS=123456\n"
        f"DATABASE_PATH={database_path}\n"
        f"CAPTCHA_DIR={captcha_dir}\n",
        encoding="utf-8",
    )
    view = ScriptView(lambda _: "", lambda _: None)

    with create_application(env_file, view=view) as application:
        admin = UserRepository(application.database).get_by_telegram_id(123456)
        assert admin is not None
        assert admin.role is UserRole.ADMIN
        assert admin.status is UserStatus.ACTIVE
        assert application.view is view

    assert not (captcha_dir / "current_captcha.jpg").exists()

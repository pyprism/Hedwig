import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


REGISTER_URL = "/api/accounts/users/register/"
ME_URL = "/api/accounts/users/me/"


def test_first_user_registration_becomes_superuser(api_client, settings):
    settings.REGISTRATION_OPEN = True

    response = api_client.post(
        REGISTER_URL,
        {
            "username": "founder",
            "email": "founder@example.com",
            "password": "Cor7rect-Horse-Battery",
        },
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(username="founder")
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.must_change_password is False
    assert user.check_password("Cor7rect-Horse-Battery")


def test_second_registration_blocked_when_closed(api_client, settings, staff_user):
    settings.REGISTRATION_OPEN = False

    response = api_client.post(
        REGISTER_URL,
        {
            "username": "latecomer",
            "email": "latecomer@example.com",
            "password": "Cor7rect-Horse-Battery",
        },
        format="json",
    )

    assert response.status_code == 403
    assert not User.objects.filter(username="latecomer").exists()


def test_second_registration_allowed_when_open_and_not_staff(
    api_client, settings, staff_user
):
    settings.REGISTRATION_OPEN = True

    response = api_client.post(
        REGISTER_URL,
        {
            "username": "newbie",
            "email": "newbie@example.com",
            "password": "Cor7rect-Horse-Battery",
        },
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(username="newbie")
    assert user.is_staff is False
    assert user.is_superuser is False


def test_me_get_returns_current_user(api_client, regular_user):
    api_client.force_authenticate(regular_user)

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.data["username"] == regular_user.username


def test_me_patch_updates_display_name(api_client, regular_user):
    api_client.force_authenticate(regular_user)

    response = api_client.patch(ME_URL, {"display_name": "New Name"}, format="json")

    assert response.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.display_name == "New Name"


def test_me_patch_cannot_escalate_privileges(api_client, regular_user):
    api_client.force_authenticate(regular_user)

    response = api_client.patch(ME_URL, {"is_staff": True}, format="json")

    assert response.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.is_staff is False


def test_me_patch_cannot_change_username_or_email(api_client, regular_user):
    api_client.force_authenticate(regular_user)

    response = api_client.patch(
        ME_URL,
        {"username": "new-name", "email": "new@example.com"},
        format="json",
    )

    assert response.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.username == "regular"
    assert regular_user.email == "regular@example.com"


def test_user_list_unauthenticated_rejected(api_client):
    response = api_client.get("/api/accounts/users/")

    assert response.status_code == 401


def test_user_list_staff_sees_all(api_client, staff_user, regular_user, other_user):
    api_client.force_authenticate(staff_user)

    response = api_client.get("/api/accounts/users/")

    assert response.status_code == 200
    usernames = {row["username"] for row in response.data["results"]}
    assert {
        staff_user.username,
        regular_user.username,
        other_user.username,
    } <= usernames


def test_user_list_regular_sees_only_self(api_client, regular_user, other_user):
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/accounts/users/")

    assert response.status_code == 200
    usernames = {row["username"] for row in response.data["results"]}
    assert usernames == {regular_user.username}


def test_last_seen_updates_on_authenticated_request(api_client, regular_user):
    assert regular_user.last_seen_at is None
    assert api_client.login(username="regular", password="regularpass123")

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.last_seen_at is not None


def test_must_change_password_blocks_other_actions(api_client, regular_user):
    regular_user.must_change_password = True
    regular_user.save(update_fields=["must_change_password"])
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/accounts/users/")

    assert response.status_code == 403


def test_change_password_clears_must_change_flag(api_client, regular_user):
    regular_user.must_change_password = True
    regular_user.save(update_fields=["must_change_password"])
    api_client.force_authenticate(regular_user)

    response = api_client.post(
        "/api/accounts/users/change-password/",
        {
            "current_password": "regularpass123",
            "new_password": "New-Cor7rect-Horse-Battery",
        },
        format="json",
    )

    assert response.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.must_change_password is False
    assert regular_user.check_password("New-Cor7rect-Horse-Battery")


def test_token_verify_and_blacklist_routes(api_client, regular_user):
    login = api_client.post(
        "/api/token/",
        {"username": "regular", "password": "regularpass123"},
        format="json",
    )
    assert login.status_code == 200

    verify = api_client.post(
        "/api/token/verify/",
        {"token": login.data["access"]},
        format="json",
    )
    assert verify.status_code == 200

    blacklist = api_client.post(
        "/api/token/blacklist/",
        {"refresh": login.data["refresh"]},
        format="json",
    )
    assert blacklist.status_code == 200

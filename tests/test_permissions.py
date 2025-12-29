from types import SimpleNamespace

from utils.permissions import is_staff_user


class DummyPerms:
    def __init__(self, manage_guild: bool = False) -> None:
        self.manage_guild = manage_guild


def test_is_staff_user_with_role_ids():
    settings = SimpleNamespace(staff_role_ids={1, 2, 3})
    user = SimpleNamespace(roles=[SimpleNamespace(id=2)], guild_permissions=DummyPerms(False))
    assert is_staff_user(user, settings)


def test_is_staff_user_with_manage_guild():
    settings = SimpleNamespace(staff_role_ids=set())
    user = SimpleNamespace(roles=[], guild_permissions=DummyPerms(True))
    assert is_staff_user(user, settings)


def test_is_staff_user_false_when_no_match():
    settings = SimpleNamespace(staff_role_ids={1})
    user = SimpleNamespace(roles=[SimpleNamespace(id=99)], guild_permissions=DummyPerms(False))
    assert not is_staff_user(user, settings)

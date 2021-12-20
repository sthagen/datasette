"""
Tests for the datasette.app.Datasette class
"""
from datasette.app import Datasette
from itsdangerous import BadSignature
from .fixtures import app_client
import pytest


@pytest.fixture
def datasette(app_client):
    return app_client.ds


def test_get_database(datasette):
    db = datasette.get_database("fixtures")
    assert "fixtures" == db.name
    with pytest.raises(KeyError):
        datasette.get_database("missing")


def test_get_database_no_argument(datasette):
    # Returns the first available database:
    db = datasette.get_database()
    assert "fixtures" == db.name


@pytest.mark.parametrize("value", ["hello", 123, {"key": "value"}])
@pytest.mark.parametrize("namespace", [None, "two"])
def test_sign_unsign(datasette, value, namespace):
    extra_args = [namespace] if namespace else []
    signed = datasette.sign(value, *extra_args)
    assert value != signed
    assert value == datasette.unsign(signed, *extra_args)
    with pytest.raises(BadSignature):
        datasette.unsign(signed[:-1] + ("!" if signed[-1] != "!" else ":"))


@pytest.mark.parametrize(
    "setting,expected",
    (
        ("base_url", "/"),
        ("max_csv_mb", 100),
        ("allow_csv_stream", True),
    ),
)
def test_datasette_setting(datasette, setting, expected):
    assert datasette.setting(setting) == expected


@pytest.mark.asyncio
async def test_datasette_constructor():
    ds = Datasette()
    databases = (await ds.client.get("/-/databases.json")).json()
    assert databases == [
        {
            "name": "_memory",
            "path": None,
            "size": 0,
            "is_mutable": False,
            "is_memory": True,
            "hash": None,
        }
    ]

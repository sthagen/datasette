from bs4 import BeautifulSoup as Soup
import json
import pytest
import re
from .fixtures import make_app_client, app_client


@pytest.fixture
def canned_write_client():
    with make_app_client(
        extra_databases={"data.db": "create table names (name text)"},
        metadata={
            "databases": {
                "data": {
                    "queries": {
                        "canned_read": {"sql": "select * from names"},
                        "add_name": {
                            "sql": "insert into names (name) values (:name)",
                            "write": True,
                            "on_success_redirect": "/data/add_name?success",
                        },
                        "add_name_specify_id": {
                            "sql": "insert into names (rowid, name) values (:rowid, :name)",
                            "write": True,
                            "on_error_redirect": "/data/add_name_specify_id?error",
                        },
                        "delete_name": {
                            "sql": "delete from names where rowid = :rowid",
                            "write": True,
                            "on_success_message": "Name deleted",
                            "allow": {"id": "root"},
                        },
                        "update_name": {
                            "sql": "update names set name = :name where rowid = :rowid",
                            "params": ["rowid", "name", "extra"],
                            "write": True,
                        },
                    }
                }
            }
        },
    ) as client:
        yield client


def test_canned_query_with_named_parameter(app_client):
    response = app_client.get("/fixtures/neighborhood_search.json?text=town")
    assert [
        ["Corktown", "Detroit", "MI"],
        ["Downtown", "Los Angeles", "CA"],
        ["Downtown", "Detroit", "MI"],
        ["Greektown", "Detroit", "MI"],
        ["Koreatown", "Los Angeles", "CA"],
        ["Mexicantown", "Detroit", "MI"],
    ] == response.json["rows"]


def test_insert(canned_write_client):
    response = canned_write_client.post(
        "/data/add_name",
        {"name": "Hello"},
        allow_redirects=False,
        csrftoken_from=True,
        cookies={"foo": "bar"},
    )
    assert 302 == response.status
    assert "/data/add_name?success" == response.headers["Location"]
    messages = canned_write_client.ds.unsign(
        response.cookies["ds_messages"], "messages"
    )
    assert [["Query executed, 1 row affected", 1]] == messages


@pytest.mark.parametrize(
    "query_name,expect_csrf_hidden_field",
    [
        ("canned_read", False),
        ("add_name_specify_id", True),
        ("add_name", True),
    ],
)
def test_canned_query_form_csrf_hidden_field(
    canned_write_client, query_name, expect_csrf_hidden_field
):
    response = canned_write_client.get(f"/data/{query_name}")
    html = response.text
    fragment = '<input type="hidden" name="csrftoken" value="'
    if expect_csrf_hidden_field:
        assert fragment in html
    else:
        assert fragment not in html


def test_insert_with_cookies_requires_csrf(canned_write_client):
    response = canned_write_client.post(
        "/data/add_name",
        {"name": "Hello"},
        allow_redirects=False,
        cookies={"foo": "bar"},
    )
    assert 403 == response.status


def test_insert_no_cookies_no_csrf(canned_write_client):
    response = canned_write_client.post(
        "/data/add_name", {"name": "Hello"}, allow_redirects=False
    )
    assert 302 == response.status
    assert "/data/add_name?success" == response.headers["Location"]


def test_custom_success_message(canned_write_client):
    response = canned_write_client.post(
        "/data/delete_name",
        {"rowid": 1},
        cookies={"ds_actor": canned_write_client.actor_cookie({"id": "root"})},
        allow_redirects=False,
        csrftoken_from=True,
    )
    assert 302 == response.status
    messages = canned_write_client.ds.unsign(
        response.cookies["ds_messages"], "messages"
    )
    assert [["Name deleted", 1]] == messages


def test_insert_error(canned_write_client):
    canned_write_client.post("/data/add_name", {"name": "Hello"}, csrftoken_from=True)
    response = canned_write_client.post(
        "/data/add_name_specify_id",
        {"rowid": 1, "name": "Should fail"},
        allow_redirects=False,
        csrftoken_from=True,
    )
    assert 302 == response.status
    assert "/data/add_name_specify_id?error" == response.headers["Location"]
    messages = canned_write_client.ds.unsign(
        response.cookies["ds_messages"], "messages"
    )
    assert [["UNIQUE constraint failed: names.rowid", 3]] == messages
    # How about with a custom error message?
    canned_write_client.ds._metadata["databases"]["data"]["queries"][
        "add_name_specify_id"
    ]["on_error_message"] = "ERROR"
    response = canned_write_client.post(
        "/data/add_name_specify_id",
        {"rowid": 1, "name": "Should fail"},
        allow_redirects=False,
        csrftoken_from=True,
    )
    assert [["ERROR", 3]] == canned_write_client.ds.unsign(
        response.cookies["ds_messages"], "messages"
    )


def test_custom_params(canned_write_client):
    response = canned_write_client.get("/data/update_name?extra=foo")
    assert '<input type="text" id="qp3" name="extra" value="foo">' in response.text


def test_vary_header(canned_write_client):
    # These forms embed a csrftoken so they should be served with Vary: Cookie
    assert "vary" not in canned_write_client.get("/data").headers
    assert "Cookie" == canned_write_client.get("/data/update_name").headers["vary"]


def test_json_post_body(canned_write_client):
    response = canned_write_client.post(
        "/data/add_name",
        body=json.dumps({"name": ["Hello", "there"]}),
        allow_redirects=False,
    )
    assert 302 == response.status
    assert "/data/add_name?success" == response.headers["Location"]
    rows = canned_write_client.get("/data/names.json?_shape=array").json
    assert rows == [{"rowid": 1, "name": "['Hello', 'there']"}]


@pytest.mark.parametrize(
    "headers,body,querystring",
    (
        (None, "name=NameGoesHere", "?_json=1"),
        ({"Accept": "application/json"}, "name=NameGoesHere", None),
        (None, "name=NameGoesHere&_json=1", None),
        (None, '{"name": "NameGoesHere", "_json": 1}', None),
    ),
)
def test_json_response(canned_write_client, headers, body, querystring):
    response = canned_write_client.post(
        "/data/add_name" + (querystring or ""),
        body=body,
        allow_redirects=False,
        headers=headers,
    )
    assert 200 == response.status
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json == {
        "ok": True,
        "message": "Query executed, 1 row affected",
        "redirect": "/data/add_name?success",
    }
    rows = canned_write_client.get("/data/names.json?_shape=array").json
    assert rows == [{"rowid": 1, "name": "NameGoesHere"}]


def test_canned_query_permissions_on_database_page(canned_write_client):
    # Without auth only shows three queries
    query_names = {
        q["name"] for q in canned_write_client.get("/data.json").json["queries"]
    }
    assert {
        "canned_read",
        "add_name",
        "add_name_specify_id",
        "update_name",
        "from_async_hook",
        "from_hook",
    } == query_names

    # With auth shows four
    response = canned_write_client.get(
        "/data.json",
        cookies={"ds_actor": canned_write_client.actor_cookie({"id": "root"})},
    )
    assert 200 == response.status
    query_names_and_private = sorted(
        [
            {"name": q["name"], "private": q["private"]}
            for q in response.json["queries"]
        ],
        key=lambda q: q["name"],
    )
    assert query_names_and_private == [
        {"name": "add_name", "private": False},
        {"name": "add_name_specify_id", "private": False},
        {"name": "canned_read", "private": False},
        {"name": "delete_name", "private": True},
        {"name": "from_async_hook", "private": False},
        {"name": "from_hook", "private": False},
        {"name": "update_name", "private": False},
    ]


def test_canned_query_permissions(canned_write_client):
    assert 403 == canned_write_client.get("/data/delete_name").status
    assert 200 == canned_write_client.get("/data/update_name").status
    cookies = {"ds_actor": canned_write_client.actor_cookie({"id": "root"})}
    assert 200 == canned_write_client.get("/data/delete_name", cookies=cookies).status
    assert 200 == canned_write_client.get("/data/update_name", cookies=cookies).status


@pytest.fixture(scope="session")
def magic_parameters_client():
    with make_app_client(
        extra_databases={"data.db": "create table logs (line text)"},
        metadata={
            "databases": {
                "data": {
                    "queries": {
                        "runme_post": {"sql": "", "write": True},
                        "runme_get": {"sql": ""},
                    }
                }
            }
        },
    ) as client:
        yield client


@pytest.mark.parametrize(
    "magic_parameter,expected_re",
    [
        ("_actor_id", "root"),
        ("_header_host", "localhost"),
        ("_header_not_a_thing", ""),
        ("_cookie_foo", "bar"),
        ("_now_epoch", r"^\d+$"),
        ("_now_date_utc", r"^\d{4}-\d{2}-\d{2}$"),
        ("_now_datetime_utc", r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
        ("_random_chars_1", r"^\w$"),
        ("_random_chars_10", r"^\w{10}$"),
    ],
)
def test_magic_parameters(magic_parameters_client, magic_parameter, expected_re):
    magic_parameters_client.ds._metadata["databases"]["data"]["queries"]["runme_post"][
        "sql"
    ] = f"insert into logs (line) values (:{magic_parameter})"
    magic_parameters_client.ds._metadata["databases"]["data"]["queries"]["runme_get"][
        "sql"
    ] = f"select :{magic_parameter} as result"
    cookies = {
        "ds_actor": magic_parameters_client.actor_cookie({"id": "root"}),
        "foo": "bar",
    }
    # Test the GET version
    get_response = magic_parameters_client.get(
        "/data/runme_get.json?_shape=array", cookies=cookies
    )
    get_actual = get_response.json[0]["result"]
    assert re.match(expected_re, str(get_actual))
    # Test the form
    form_response = magic_parameters_client.get("/data/runme_post")
    soup = Soup(form_response.body, "html.parser")
    # The magic parameter should not be represented as a form field
    assert None is soup.find("input", {"name": magic_parameter})
    # Submit the form to create a log line
    response = magic_parameters_client.post(
        "/data/runme_post?_json=1", {}, csrftoken_from=True, cookies=cookies
    )
    assert response.json == {
        "ok": True,
        "message": "Query executed, 1 row affected",
        "redirect": None,
    }
    post_actual = magic_parameters_client.get(
        "/data/logs.json?_sort_desc=rowid&_shape=array"
    ).json[0]["line"]
    assert re.match(expected_re, post_actual)


@pytest.mark.parametrize("use_csrf", [True, False])
@pytest.mark.parametrize("return_json", [True, False])
def test_magic_parameters_csrf_json(magic_parameters_client, use_csrf, return_json):
    magic_parameters_client.ds._metadata["databases"]["data"]["queries"]["runme_post"][
        "sql"
    ] = "insert into logs (line) values (:_header_host)"
    qs = ""
    if return_json:
        qs = "?_json=1"
    response = magic_parameters_client.post(
        f"/data/runme_post{qs}",
        {},
        csrftoken_from=use_csrf or None,
        allow_redirects=False,
    )
    if return_json:
        assert response.status == 200
        assert response.json["ok"], response.json
    else:
        assert response.status == 302
        messages = magic_parameters_client.ds.unsign(
            response.cookies["ds_messages"], "messages"
        )
        assert [["Query executed, 1 row affected", 1]] == messages
    post_actual = magic_parameters_client.get(
        "/data/logs.json?_sort_desc=rowid&_shape=array"
    ).json[0]["line"]
    assert post_actual == "localhost"


def test_magic_parameters_cannot_be_used_in_arbitrary_queries(magic_parameters_client):
    response = magic_parameters_client.get(
        "/data.json?sql=select+:_header_host&_shape=array"
    )
    assert 400 == response.status
    assert "You did not supply a value for binding 1." == response.json["error"]

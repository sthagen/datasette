"""
Tests to ensure certain things are documented.
"""
from click.testing import CliRunner
from datasette import app
from datasette.cli import cli
from datasette.filters import Filters
from pathlib import Path
import pytest
import re

docs_path = Path(__file__).parent.parent / "docs"
label_re = re.compile(r"\.\. _([^\s:]+):")


def get_headings(content, underline="-"):
    heading_re = re.compile(r"(\w+)(\([^)]*\))?\n\{}+\n".format(underline))
    return {h[0] for h in heading_re.findall(content)}


def get_labels(filename):
    content = (docs_path / filename).read_text()
    return set(label_re.findall(content))


@pytest.fixture(scope="session")
def settings_headings():
    return get_headings((docs_path / "settings.rst").read_text(), "~")


@pytest.mark.parametrize("setting", app.SETTINGS)
def test_settings_are_documented(settings_headings, setting):
    assert setting.name in settings_headings


@pytest.mark.parametrize(
    "name,filename",
    (
        ("serve", "datasette-serve-help.txt"),
        ("package", "datasette-package-help.txt"),
        ("publish heroku", "datasette-publish-heroku-help.txt"),
        ("publish cloudrun", "datasette-publish-cloudrun-help.txt"),
    ),
)
def test_help_includes(name, filename):
    expected = (docs_path / filename).read_text()
    runner = CliRunner()
    result = runner.invoke(cli, name.split() + ["--help"], terminal_width=88)
    actual = f"$ datasette {name} --help\n\n{result.output}"
    # actual has "Usage: cli package [OPTIONS] FILES"
    # because it doesn't know that cli will be aliased to datasette
    expected = expected.replace("Usage: datasette", "Usage: cli")
    assert expected == actual, "Run python update-docs-help.py to fix this"


@pytest.fixture(scope="session")
def plugin_hooks_content():
    return (docs_path / "plugin_hooks.rst").read_text()


@pytest.mark.parametrize(
    "plugin", [name for name in dir(app.pm.hook) if not name.startswith("_")]
)
def test_plugin_hooks_are_documented(plugin, plugin_hooks_content):
    headings = get_headings(plugin_hooks_content, "-")
    assert plugin in headings
    hook_caller = getattr(app.pm.hook, plugin)
    arg_names = [a for a in hook_caller.spec.argnames if a != "__multicall__"]
    # Check for plugin_name(arg1, arg2, arg3)
    expected = f"{plugin}({', '.join(arg_names)})"
    assert (
        expected in plugin_hooks_content
    ), f"Missing from plugin hook documentation: {expected}"


@pytest.fixture(scope="session")
def documented_views():
    view_labels = set()
    for filename in docs_path.glob("*.rst"):
        for label in get_labels(filename):
            first_word = label.split("_")[0]
            if first_word.endswith("View"):
                view_labels.add(first_word)
    # We deliberately don't document these:
    view_labels.update(("PatternPortfolioView", "AuthTokenView"))
    return view_labels


@pytest.mark.parametrize("view_class", [v for v in dir(app) if v.endswith("View")])
def test_view_classes_are_documented(documented_views, view_class):
    assert view_class in documented_views


@pytest.fixture(scope="session")
def documented_table_filters():
    json_api_rst = (docs_path / "json_api.rst").read_text()
    section = json_api_rst.split(".. _table_arguments:")[-1]
    # Lines starting with ``?column__exact= are docs for filters
    return {
        line.split("__")[1].split("=")[0]
        for line in section.split("\n")
        if line.startswith("``?column__")
    }


@pytest.mark.parametrize("filter", [f.key for f in Filters._filters])
def test_table_filters_are_documented(documented_table_filters, filter):
    assert filter in documented_table_filters

"""
Tests for the exclude functionality of pytest-persistence plugin
"""
import json
import pickle
import pytest

pytest_plugins = ["pytester"]


CONFTEST = """
import json
from pathlib import Path
import pytest
from pytest_persistence import exclude

COUNTS_FILE = Path("call_counts.json")

def _track(name):
    data = json.loads(COUNTS_FILE.read_text()) if COUNTS_FILE.exists() else {}
    data[name] = data.get(name, 0) + 1
    COUNTS_FILE.write_text(json.dumps(data))

@exclude
@pytest.fixture
def excluded_fixture():
    _track("excluded_fixture")
    return "excluded_value"

@pytest.fixture
def non_excluded_fixture():
    _track("non_excluded_fixture")
    return "non_excluded_value"

@pytest.fixture
def dependent_fixture(excluded_fixture):
    _track("dependent_fixture")
    return f"depends_on_{excluded_fixture}"

@pytest.fixture
def deep_dependent_fixture(dependent_fixture):
    _track("deep_dependent_fixture")
    return f"deep_{dependent_fixture}"

@exclude
@pytest.fixture
def explicitly_excluded_child(excluded_fixture):
    _track("explicitly_excluded_child")
    return f"explicit_{excluded_fixture}"

@pytest.fixture
def multiple_parents_fixture(excluded_fixture, non_excluded_fixture):
    _track("multiple_parents_fixture")
    return f"{excluded_fixture}_{non_excluded_fixture}"

@exclude
@pytest.fixture(scope="session")
def excluded_session_fixture():
    _track("excluded_session_fixture")
    return "session_excluded"

@exclude
@pytest.fixture(scope="module")
def excluded_module_fixture():
    _track("excluded_module_fixture")
    return "module_excluded"

@exclude
@pytest.fixture(scope="function")
def excluded_function_fixture():
    _track("excluded_function_fixture")
    return "function_excluded"

@pytest.fixture
def parent_fixture():
    _track("parent_fixture")
    return "parent_value"

@exclude
@pytest.fixture
def excluded_child_fixture(parent_fixture):
    _track("excluded_child_fixture")
    return f"child_{parent_fixture}"
"""


def get_counts(pytester):
    counts_file = pytester.path / "call_counts.json"
    if counts_file.exists():
        return json.loads(counts_file.read_text())
    return {}


def load_pickle(pytester, filename="fixtures.pkl"):
    with open(pytester.path / filename, "rb") as f:
        return pickle.load(f)


def fixture_stored(data, fixture_name):
    """Check if a fixture value is stored in any scope of the pickle data"""
    for scope in ("session", "package", "module", "class", "function"):
        scope_data = data.get(scope, {})
        if scope == "session":
            for key in scope_data:
                if key.startswith(f"('{fixture_name}',"):
                    return True
        else:
            for node_fixtures in scope_data.values():
                if isinstance(node_fixtures, dict):
                    for key in node_fixtures:
                        if key.startswith(f"('{fixture_name}',"):
                            return True
    return False


# Basic Tests

def test_exclude_decorator_exists():
    """Test 1: Verify that exclude decorator is available for import"""
    from pytest_persistence import exclude
    assert callable(exclude)
    assert hasattr(exclude, '__call__')


def test_excluded_fixture_not_stored(pytester):
    """Test 2: Verify that excluded fixture is not stored during --store"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_excluded_fixture(excluded_fixture):
            assert excluded_fixture == "excluded_value"
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    data = load_pickle(pytester)
    assert not fixture_stored(data, "excluded_fixture"), \
        "excluded_fixture should not be stored in pickle file"


def test_excluded_fixture_recreated_on_load(pytester):
    """Test 3: Verify that excluded fixture is recreated during --load"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_excluded_fixture(excluded_fixture):
            assert excluded_fixture == "excluded_value"
    """)

    # Store phase
    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get("excluded_fixture") == 1, \
        "excluded_fixture should be created once during store"

    # Load phase - should be recreated
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get("excluded_fixture") == 2, \
        "excluded_fixture should be recreated once during load"


def test_non_excluded_fixture_stored(pytester):
    """Test 4: Verify that non-excluded fixture is normally stored and loaded from pickle"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_non_excluded_fixture(non_excluded_fixture):
            assert non_excluded_fixture == "non_excluded_value"
    """)

    # Store phase
    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get("non_excluded_fixture") == 1, \
        "non_excluded_fixture should be created once during store"

    data = load_pickle(pytester)
    assert fixture_stored(data, "non_excluded_fixture"), \
        "non_excluded_fixture should be stored in pickle"

    # Load phase - should NOT be recreated (loaded from pickle)
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get("non_excluded_fixture") == 1, \
        "non_excluded_fixture should be loaded from pickle, not recreated"


# Dependency Tests

def test_dependent_fixture_excluded(pytester):
    """Test 5: Verify that fixture dependent on excluded is also excluded"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_dependent_fixture(dependent_fixture):
            assert "depends_on_excluded_value" in dependent_fixture
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get("dependent_fixture") == 1

    data = load_pickle(pytester)
    assert not fixture_stored(data, "dependent_fixture"), \
        "dependent_fixture should not be stored (excluded by dependency)"

    # Load phase - should be recreated
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    counts = get_counts(pytester)
    assert counts.get("dependent_fixture") == 2, "dependent_fixture should be recreated"
    assert counts.get("excluded_fixture") == 2, "excluded_fixture should be recreated"


def test_dependency_tree_excluded(pytester):
    """Test 6: Verify that entire dependency tree is excluded (3+ levels)"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_deep_dependent_fixture(deep_dependent_fixture):
            assert "deep_depends_on_excluded_value" in deep_dependent_fixture
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    counts = get_counts(pytester)
    assert counts.get("deep_dependent_fixture") == 1
    assert counts.get("dependent_fixture") == 1
    assert counts.get("excluded_fixture") == 1

    data = load_pickle(pytester)
    assert not fixture_stored(data, "excluded_fixture")
    assert not fixture_stored(data, "dependent_fixture")
    assert not fixture_stored(data, "deep_dependent_fixture")

    # Load phase - all should be recreated
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    counts = get_counts(pytester)
    assert counts.get("deep_dependent_fixture") == 2, "deep_dependent_fixture should be recreated"
    assert counts.get("dependent_fixture") == 2, "dependent_fixture should be recreated"
    assert counts.get("excluded_fixture") == 2, "excluded_fixture should be recreated"


def test_multiple_parents_one_excluded(pytester):
    """Test 7: Verify behavior when fixture has multiple parents and one is excluded"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_multiple_parents_fixture(multiple_parents_fixture):
            assert "excluded_value" in multiple_parents_fixture
            assert "non_excluded_value" in multiple_parents_fixture
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get("multiple_parents_fixture") == 1

    data = load_pickle(pytester)
    assert not fixture_stored(data, "multiple_parents_fixture"), \
        "multiple_parents_fixture should not be stored (has excluded parent)"
    assert fixture_stored(data, "non_excluded_fixture"), \
        "non_excluded_fixture should be stored"

    # Load phase
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    counts = get_counts(pytester)
    assert counts.get("multiple_parents_fixture") == 2, "multiple_parents_fixture should be recreated"
    assert counts.get("excluded_fixture") == 2, "excluded_fixture should be recreated"
    assert counts.get("non_excluded_fixture") == 1, "non_excluded_fixture should be loaded from pickle"


# Warning Tests

def test_warning_for_implicit_exclusion(pytester):
    """Test 8: Verify that warning is shown for implicitly excluded fixture"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_dependent_fixture(dependent_fixture):
            assert "depends_on_excluded_value" in dependent_fixture
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    output = result.stdout.str() + result.stderr.str()
    assert "dependent_fixture" in output
    assert "excluded" in output.lower() or "dependency" in output.lower()


def test_no_warning_for_explicit_exclusion(pytester):
    """Test 9: Verify that NO warning is shown for explicitly excluded fixture"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_explicitly_excluded_child(explicitly_excluded_child):
            assert "explicit_excluded_value" in explicitly_excluded_child
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    output = result.stdout.str() + result.stderr.str()
    assert "excluded due to dependency" not in output


def test_warning_contains_parent_name(pytester):
    """Test 10: Verify that warning contains parent fixture name"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_dependent_fixture(dependent_fixture):
            assert "depends_on_excluded_value" in dependent_fixture
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    output = result.stdout.str() + result.stderr.str()
    assert "dependent_fixture" in output
    assert "excluded_fixture" in output


# Scope Tests

@pytest.mark.parametrize("fixture_name,scope,expected_value", [
    ("excluded_session_fixture", "session", "session_excluded"),
    ("excluded_module_fixture", "module", "module_excluded"),
    ("excluded_function_fixture", "function", "function_excluded"),
])
def test_exclude_scoped_fixtures(pytester, fixture_name, scope, expected_value):
    """Test 14-16: Verify functionality for different scope fixtures"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(f"""
        def test_use_{fixture_name}({fixture_name}):
            assert {fixture_name} == "{expected_value}"
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get(fixture_name) == 1, \
        f"{fixture_name} should be created once"

    data = load_pickle(pytester)
    assert not fixture_stored(data, fixture_name), \
        f"{fixture_name} should not be stored"

    # Load phase - should be recreated
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)
    assert get_counts(pytester).get(fixture_name) == 2, \
        f"{fixture_name} should be recreated"


# Edge Cases

def test_excluded_fixture_executes_normally(pytester):
    """Test 17: Verify that excluded fixture executes normally"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_excluded_fixture(excluded_fixture):
            assert excluded_fixture == "excluded_value"
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)


def test_parent_loaded_child_recreated(pytester):
    """Test 18: Verify that parent is loaded from pickle and child is recreated"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_excluded_child_fixture(excluded_child_fixture):
            assert "child_parent_value" in excluded_child_fixture
    """)

    # Store phase
    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    counts = get_counts(pytester)
    assert counts.get("parent_fixture") == 1, "parent_fixture should be created once"
    assert counts.get("excluded_child_fixture") == 1, "excluded_child_fixture should be created once"

    data = load_pickle(pytester)
    assert fixture_stored(data, "parent_fixture"), "parent_fixture should be stored in pickle"
    assert not fixture_stored(data, "excluded_child_fixture"), "excluded_child_fixture should NOT be stored"

    # Load phase
    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    counts = get_counts(pytester)
    assert counts.get("parent_fixture") == 1, "parent_fixture should be loaded from pickle, not recreated"
    assert counts.get("excluded_child_fixture") == 2, "excluded_child_fixture should be recreated"


def test_backward_compatibility(pytester):
    """Test 19: Verify that existing functionality works without changes"""
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("""
        def test_use_non_excluded_fixture(non_excluded_fixture):
            assert non_excluded_fixture == "non_excluded_value"
    """)

    result = pytester.runpytest("--store", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

    result = pytester.runpytest("--load", "fixtures.pkl", "-v")
    result.assert_outcomes(passed=1)

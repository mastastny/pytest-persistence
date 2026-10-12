"""
pytest-persistence plugin for storing and loading fixture results
"""


def exclude(func):
    """
    Decorator to exclude a fixture from persistence.

    When applied to a fixture, it will:
    - Not be stored during --store
    - Be recreated during --load (parent fixtures will be loaded from file)
    - Automatically exclude all dependent fixtures

    Example:
        @pytest_persistence.exclude
        @pytest.fixture
        def non_persistent_fixture():
            return expensive_operation()
    """
    func._pytest_persistence_exclude = True
    # Also mark the underlying function if func is a pytest FixtureFunctionDefinition
    # wrapper, because fixturedef.func points to the unwrapped function.
    wrapped = getattr(func, "__wrapped__", None)
    if wrapped is not None:
        wrapped._pytest_persistence_exclude = True
    return func


__all__ = ["exclude"]

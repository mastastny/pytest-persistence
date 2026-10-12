# pytest-persistence

Pytest plugin for persistent fixtures.

## Installation

In a Python environment do:

    python -m pip install pytest-persistence

## Usage

To store fixtures to file run tests with `--store {file_path}`:

    python -m pytest --store {file_path}

To load fixtures from file run tests with `--load {file_path}`:

    python -m pytest --load {file_path}

**BEWARE** When this plugin is in use cleanup of all the fixtures is **not**
executed. This is necessary to successfully run tests with `--load`. However it
is important to keep this fact in mind.

## Excluding Fixtures

You can exclude specific fixtures from persistence using the `@pytest_persistence.exclude` decorator:

```python
import pytest
import pytest_persistence

@pytest_persistence.exclude
@pytest.fixture
def non_persistent_fixture():
    return expensive_operation()
```

When a fixture is excluded:
- It will **not be stored** during `--store`
- It will be **recreated** during `--load` (parent fixtures will be loaded from file)
- All **dependent fixtures are automatically excluded**
- A warning is shown for implicitly excluded fixtures

### Example with Dependencies

```python
import pytest
from pytest_persistence import exclude

@exclude
@pytest.fixture
def excluded_fixture():
    return "excluded"

@pytest.fixture
def dependent_fixture(excluded_fixture):
    return f"depends on {excluded_fixture}"

@pytest.fixture  
def another_dependent(dependent_fixture):
    return f"also depends: {dependent_fixture}"
```

When running with `--store`, you'll see:

```
Warning: Fixture 'dependent_fixture' excluded due to dependency on excluded fixture 'excluded_fixture'
Warning: Fixture 'another_dependent' excluded due to dependency on excluded fixture 'dependent_fixture'
```

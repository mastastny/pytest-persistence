import os
import pickle
from pprint import pformat
from typing import Any
import warnings

import pytest
from _pytest.fixtures import pytest_fixture_setup as fixture_result

from pytest_persistence.XDistScheduling import XDistScheduling


def pytest_addoption(parser):
    """
    Add option to store/load fixture results into file
    """
    parser.addoption("--store", action="store", default=False, help="Store config")
    parser.addoption("--load", action="store", default=False, help="Load config")


class Plugin:
    """
    Pytest persistence plugin
    """

    def __init__(self):
        self.output: dict[str, Any] = {
            "session": {},
            "package": {},
            "module": {},
            "class": {},
            "function": {},
            "workers": {},
            "tests": {},
        }
        self.input: dict[str, Any] = {}
        self.unable_to_pickle: set[tuple[str, str, str]] = set()
        self.pickled_fixtures: set[tuple[str, str, str]] = set()
        self.excluded_fixtures: set[str] = set()
        self.dependency_excluded_fixtures: dict[str, str] = {}

    def pytest_sessionstart(self, session):
        """
        Called after the ``Session`` object has been created and before performing collection
        and entering the run test loop. Checks whether '--load' option is present. If it is, load
        fixtures results from given file.
        """
        if file := session.config.getoption("--store"):
            if os.path.isfile(file):
                raise FileExistsError("This file already exists")
        if file := session.config.getoption("--load"):
            with open(file, "rb") as f:
                self.input = pickle.load(f)

    def is_fixture_excluded(self, fixturedef):
        """Check if a fixture has the @pytest_persistence.exclude decorator"""
        return getattr(fixturedef.func, "_pytest_persistence_exclude", False)

    def build_exclusion_set(self, fixturedef, fixture_manager):
        """
        Recursively check if a fixture or any of its dependencies are excluded.

        Returns:
            bool: True if this fixture or any of its dependencies are excluded
        """
        fixture_name = fixturedef.argname

        if (
            fixture_name in self.excluded_fixtures
            or fixture_name in self.dependency_excluded_fixtures
        ):
            return True

        is_explicitly_excluded = self.is_fixture_excluded(fixturedef)

        if is_explicitly_excluded:
            self.excluded_fixtures.add(fixture_name)

        has_excluded_dependency = False
        for arg_name in fixturedef.argnames:
            try:
                arg_fixturedef = fixture_manager._arg2fixturedefs.get(arg_name, [None])[
                    0
                ]
                if arg_fixturedef and self.build_exclusion_set(
                    arg_fixturedef, fixture_manager
                ):
                    has_excluded_dependency = True
                    if not is_explicitly_excluded:
                        self.dependency_excluded_fixtures[fixture_name] = arg_name
            except (KeyError, IndexError, AttributeError):
                continue

        return is_explicitly_excluded or has_excluded_dependency

    def emit_dependency_warnings(self):
        """Emit warnings for fixtures excluded due to dependencies"""
        for fixture_name, parent_name in sorted(
            self.dependency_excluded_fixtures.items()
        ):
            warnings.warn(
                f"Fixture '{fixture_name}' excluded due to dependency on excluded fixture '{parent_name}'",
                UserWarning,
                stacklevel=2,
            )

    def check_output(self):
        """Check if output dict can be serialized"""

        def check_fixtures(fixtures):
            to_remove = []
            for k, v in fixtures.items():
                try:
                    pickle.dumps(v)
                except Exception:
                    to_remove.append(k)
            for fixture in to_remove:
                fixtures.pop(fixture)
                if fixture in self.pickled_fixtures:
                    self.pickled_fixtures.remove(fixture)
                    self.unable_to_pickle.add(fixture)

        for scope, fixtures in self.output.items():
            if scope == "workers":
                return
            if scope == "session":
                check_fixtures(fixtures)
            else:
                for key, value in fixtures.items():
                    check_fixtures(value)

    def output_to_file(self, filename):
        """Serialize output dict into file"""
        with open(filename, "wb") as outfile:
            self.check_output()
            pickle.dump(self.output, outfile)

    def merge_dicts(self, fixtures):
        for k, v in fixtures.items():
            self.output[k].update(v)

    def pytest_sessionfinish(self, session):
        """
        Called after whole test run finished, right before returning the exit status to the system.
        Checks whether '--store' option is present. If it is, store fixtures results to given file.
        """
        if session.config.getoption("collectonly"):
            # early return if we are run with --collect-only
            return

        if session.config.getoption("--store"):
            self.emit_dependency_warnings()

        if file := session.config.getoption("--store"):
            if worker := os.getenv("PYTEST_XDIST_WORKER"):
                self.output_to_file(f"{file}_{worker}")
                return
            try:
                workers = session.config.getoption("-n")
            except ValueError:
                workers = None
            if workers:
                for i in range(workers):
                    with open(f"{file}_gw{i}", "rb") as f:
                        self.merge_dicts(pickle.load(f))
                        os.remove(f"{file}_gw{i}")
            self.output_to_file(file)
            if self.pickled_fixtures:
                print(f"\nStored fixtures:\n{pformat(self.pickled_fixtures)}")
            if self.unable_to_pickle:
                print(f"\nUnstored fixtures:\n{pformat(self.unable_to_pickle)}")

    def load_fixture(self, fixture_id, node_id):
        """
        Load fixture result
        """
        name, scope, baseid = fixture_id
        fixture_id = str((name, scope, baseid, self.input["workers"].get(node_id)))
        if scope == "session":
            if result := self.input[scope].get(fixture_id):
                return result
        else:
            if result := self.input[scope].get(node_id, {}).get(fixture_id):
                return result

    def store_fixture(self, result, fixture_id, node_id, worker_id):
        """
        Store fixture result
        """
        name, scope, baseid = fixture_id
        fixture_id = str((name, scope, baseid, worker_id))
        self.pickled_fixtures.add(fixture_id)
        if scope == "session":
            self.output[scope].update({fixture_id: result})
        else:
            if self.output[scope].get(node_id):
                self.output[scope][node_id].update({fixture_id: result})
            else:
                self.output[scope].update({node_id: {fixture_id: result}})

    def pytest_fixture_setup(self, fixturedef, request):
        """
        Perform fixture setup execution.
        If '--load' switch is present, tries to find fixture results in stored results.
        If '--store' switch is present, store fixture result.
        :returns: The return value of the fixture function.
        """
        my_cache_key = fixturedef.cache_key(request)
        worker_id = os.getenv("PYTEST_XDIST_WORKER")
        fixture_id = fixturedef.argname, fixturedef.scope, fixturedef.baseid
        node_id = request._pyfuncitem._nodeid

        if request.config.getoption("--load"):
            result = self.load_fixture(fixture_id, node_id)
            if result:
                fixturedef.cached_result = (result, my_cache_key, None)
                return result

        result = fixture_result(fixturedef, request)

        if request.config.getoption("--store"):
            fixture_manager = request._fixturemanager
            self.build_exclusion_set(fixturedef, fixture_manager)

            fixture_name = fixturedef.argname
            is_excluded = (
                fixture_name in self.excluded_fixtures
                or fixture_name in self.dependency_excluded_fixtures
            )

            if not is_excluded:
                try:
                    pickle.dumps(result)
                    self.output["workers"].update({node_id: worker_id})
                    self.store_fixture(result, fixture_id, node_id, worker_id)
                except Exception:
                    self.unable_to_pickle.add(fixture_id)

        return result

    def pytest_runtest_setup(self, item):
        worker_id = os.getenv("PYTEST_XDIST_WORKER")
        node_id = item._pyfuncitem._nodeid
        self.output["tests"].update({node_id: worker_id})

    @pytest.hookimpl(trylast=True)
    def pytest_xdist_make_scheduler(self, config, log):
        if (test_order := self.input.get("tests")) is not None:
            return XDistScheduling(config, log, test_order)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        """Cleanup skipping

        persistence functionality requires skip of cleanup during store obviously.
        Otherwise fixtures would be invalid during load when the fixture does
        something externally.

        There doesn't seem to be an interface access finlaizers, non-public API is
        in use. setupstate.stack is used to access finalizers.

        Structure of setupstate.stack is documented in SetupState class in pytest.
        It's dict of tuples.

        stack == {
            Node: (
                [*finalizers],
                exception
            )
        }

        Besides clearing setupstate.stack also cached_result must be cleared and I
        forgot why. Access to fixture is possible via closure.
        """
        needed = nextitem.listchain() if nextitem else []
        # public api unknown
        # pylint: disable=protected-access
        stack = item.session._setupstate.stack

        def fixtures(finalizers):
            """Mine fixturedefs from stack of finalizers"""
            for fin in finalizers:
                if hasattr(fin, "func"):
                    yield fin.func.__self__

                if not getattr(fin, "__closure__", None):
                    continue
                for cell in fin.__closure__:
                    if hasattr(cell, "cell_contents") and hasattr(
                        cell.cell_contents, "cached_result"
                    ):
                        yield cell.cell_contents

        for k in list(stack.keys()):
            if k not in needed:
                for i in fixtures(stack[k][0]):
                    i.cached_result = None
                    if hasattr(i, "_finalizers"):
                        i._finalizers.clear()
                stack[k][0].clear()


def pytest_configure(config):
    """
    Hook ensures that plugin works only when the --load or --store option is present.
    """
    if config.getoption("--load") or config.getoption("--store"):
        config.pluginmanager.register(Plugin())

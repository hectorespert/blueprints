# Organization and Testing Guide

This document defines how to organize folders in this repository and how to design tests for Home Assistant blueprints.

## Folder Organization

Expected structure:

- blueprints/
	- One YAML file per blueprint.
	- Use a descriptive and stable file name.
	- Example: ac_sync_setpoint_to_input_number.yaml
- tests/
	- One test_<blueprint_name>.py file per blueprint.
	- conftest.py for shared fixtures.
	- __init__.py for the tests package.
- README.md
	- Installation and test execution instructions.
- requirements-test.txt
	- Test dependencies installable with pip.
- pytest.ini
	- Global pytest configuration.

Recommended naming rules:

- Blueprint: snake_case, behavior-oriented.
- Test file: test_ prefix + blueprint name.
- Test case: test_<expected_behavior>.

## Blueprint Testing Standard

Each blueprint should include tests that cover at least:

1. Happy path: actions run when conditions are met.
2. No-op path: nothing runs when thresholds or conditions are not met.
3. Sequential changes: the automation uses the latest state/attribute value.
4. Minimal configuration and relevant input parameters.

## Technical Implementation Pattern

Use pytest with Home Assistant fixtures:

1. In tests/conftest.py, patch blueprint loading to read from the local blueprints/ folder.
2. In each test, set up the automation with async_setup_component and use_blueprint.
3. Simulate state changes with hass.states.async_set.
4. Mock services with async_mock_service.
5. Assert expected calls, payload data, and call count.

## Base Template for a New Test

1. Create test_<blueprint>.py.
2. Define base entities in an autouse fixture.
3. Add a setup_blueprint helper to avoid duplication.
4. Write explicit, behavior-focused independent test cases.
5. Assert correctly typed values (for example, float instead of string when applicable).

## Running Tests

Recommended pip-based workflow:

1. Create a virtual environment.
2. Install dependencies from requirements-test.txt.
3. Run pytest.

Commands:

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
pytest -q

## Quality Criteria Before Merge

1. All tests pass locally.
2. Every new or modified blueprint has dedicated tests.
3. Tests cover both positive and negative paths.
4. The test suite runs only with dependencies listed in requirements-test.txt.
5. Local environment files are excluded by .gitignore.

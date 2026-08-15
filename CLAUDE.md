# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A collection of Home Assistant automation blueprints (YAML) for a "Follow Me" AC
temperature control system, plus a Python/pytest test suite that exercises each
blueprint through Home Assistant's real automation engine.

## Commands

Setup (uses pip + a venv, no other package manager):

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
```

Run tests:

```bash
pytest -q
```

Run a single test file / test case:

```bash
pytest -q tests/test_ac_sync_setpoint_to_input_number.py
pytest -q tests/test_ac_sync_setpoint_to_input_number.py::test_syncs_when_change_has_user_context
```

CI (`.github/workflows/test-blueprints.yml`) runs on push/PR to `main`: installs
`requirements-test.txt` and runs `pytest -q` on Python 3.14. There is no lint step.

## Architecture

Two blueprints form a pipeline, connected through a shared `input_number` helper:

```
Remote/Dashboard → [ac_sync_setpoint_to_input_number] → input_number → [ac_follow_me] → climate.set_temperature
```

- **`blueprints/ac_sync_setpoint_to_input_number.yaml`** — Watches a `climate`
  entity's `temperature` attribute and mirrors user-initiated setpoint changes
  (physical remote or dashboard) into an `input_number` helper. This decouples
  the "user's intended temperature" from whatever the Follow Me automation is
  currently commanding, avoiding feedback loops.
- **`blueprints/ac_follow_me.yaml`** — Compares an external sensor (user's real
  location) against the AC's internal sensor and adjusts the AC setpoint to
  compensate: `setpoint = user_target - (external_temp - internal_temp) * gain`.

Both blueprints are `mode: restart` automations and rely on Jinja2 `variables:`
blocks plus `condition: template` guards rather than the `for:`/trigger options
alone — most of the actual logic (loop prevention, hysteresis, availability
checks) lives in these template conditions, so read them carefully when
modifying behavior. Key guards to be aware of when touching either blueprint:

- **Feedback-loop prevention** (`ac_sync_setpoint_to_input_number.yaml`):
  automation-caused state changes carry a `context.parent_id` with no
  `user_id`; only changes with `user_id` set or no `parent_id` at all are
  synced. Without this, Follow Me's own corrections would get synced back and
  drift the target to extremes.
- **Unavailable/unknown recovery**: when a `climate` entity comes back online
  from `unavailable`/`unknown` it reports its last stored value — both
  blueprints treat this as a spurious change, not a real setpoint update, and
  ignore it (see `trigger.from_state.state not in ['unavailable', 'unknown']`
  style guards).
- **Hysteresis / minimum-change thresholds** (`hysteresis` in `ac_follow_me`,
  `min_change` in the sync blueprint): prevent command spam from tiny sensor
  fluctuations.

## Testing pattern

`tests/conftest.py` monkeypatches Home Assistant's blueprint loader
(`DomainBlueprints._load_blueprint`) so `blueprints/*.yaml` are loaded directly
from this repo instead of a HA config directory — no fixture copies needed.

Each test file follows the same shape (see `tests/test_ac_sync_setpoint_to_input_number.py`):

1. A local `setup_blueprint(hass, config)` helper calls
   `async_setup_component` with `use_blueprint` pointing at the blueprint's
   filename and an `input:` config dict.
2. An autouse fixture seeds baseline entity states (e.g. `climate.test_ac`,
   `input_number.test_target`).
3. Tests drive behavior via `hass.states.async_set(...)` (optionally passing a
   `Context(parent_id=...)` or `Context(user_id=...)` to simulate
   automation-vs-user-initiated changes) and assert on service calls captured
   via `async_mock_service(hass, domain, service)`.

`tests/test_integration_follow_me_and_sync.py` wires both blueprints together
in the same test to verify the end-to-end pipeline, not just each blueprint in
isolation.

When adding a new blueprint or changing an existing one's behavior, cover at
minimum: happy path, no-op path (condition/threshold not met), that the latest
state/attribute value is used across sequential changes, and minimal-config
behavior — per `AGENTS.md`.

## Repo conventions (from AGENTS.md)

- One YAML file per blueprint in `blueprints/`, snake_case, behavior-oriented
  name; matching `tests/test_<blueprint_name>.py`.
- All code artifacts (blueprint descriptions, input names, Python identifiers,
  comments) are written in English.
- Every new/modified blueprint needs dedicated tests before merge; the suite
  must run using only `requirements-test.txt` dependencies.

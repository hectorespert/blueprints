"""
Tests for ac_virtual_iclean.yaml

Self-cleaning cycle for indoor units whose manufacturer function is disabled,
as happens with Bosch "I clean" on multi-split installations:

    disable rival automations → freeze (cool at the lowest setpoint) → off
    → re-enable them once the unit reports off

async_mock_service captures service calls without updating entity state, so
tests report the unit's mode back through hass.states.async_set, the way a real
integration would.
"""

import asyncio
import pytest
from datetime import timedelta
from homeassistant.core import HomeAssistant, callback
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_mock_service,
    async_fire_time_changed,
)

BLUEPRINT_PATH = "ac_virtual_iclean.yaml"

DEFAULT_INPUT = {
    "climate_entity": "climate.test_ac",
    "manual_trigger": "input_button.test_clean",
    "automations_to_pause": [
        "automation.follow_me_test_ac",
        "automation.dry_cycle_test_ac",
    ],
    "freeze_temperature": 16,
    "freeze_minutes": 12,
}


async def setup_blueprint(hass: HomeAssistant, config: dict = None) -> dict:
    """Set up the blueprint and return mocks for automation.turn_off/turn_on.

    The automation services are mocked after setup on purpose: setting up the
    automation integration registers the real ones, which would replace mocks
    registered earlier.
    """
    ok = await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": BLUEPRINT_PATH,
                    "input": config or DEFAULT_INPUT,
                }
            }
        },
    )
    assert ok
    await hass.async_block_till_done()
    return {
        "off": async_mock_service(hass, "automation", "turn_off"),
        "on": async_mock_service(hass, "automation", "turn_on"),
    }


@pytest.fixture(autouse=True)
def setup_entities(hass: HomeAssistant) -> None:
    hass.states.async_set("climate.test_ac", "off", {"temperature": 22.0})
    hass.states.async_set("input_button.test_clean", dt_util.utcnow().isoformat())
    hass.states.async_set("automation.follow_me_test_ac", "on")
    hass.states.async_set("automation.dry_cycle_test_ac", "on")


def mock_climate_services(hass: HomeAssistant) -> dict:
    """Mock every climate service the blueprint uses."""
    return {
        "hvac": async_mock_service(hass, "climate", "set_hvac_mode"),
        "temp": async_mock_service(hass, "climate", "set_temperature"),
        "off": async_mock_service(hass, "climate", "turn_off"),
    }


async def settle(hass: HomeAssistant) -> None:
    """Let pending callbacks run.

    async_block_till_done() cannot be used once the cycle is under way: it
    waits for the automation task, which is asleep in a delay, and under the
    frozen clock that timer never fires on its own, so the loop deadlocks.
    """
    for _ in range(30):
        await asyncio.sleep(0)


async def press_button(hass: HomeAssistant) -> None:
    hass.states.async_set("input_button.test_clean", dt_util.utcnow().isoformat())
    await settle(hass)


async def report_mode(hass: HomeAssistant, mode: str) -> None:
    """Simulate the integration reporting the unit's mode back."""
    hass.states.async_set("climate.test_ac", mode, {"temperature": 17.0})
    await settle(hass)


async def advance(hass: HomeAssistant, freezer, **kwargs) -> None:
    """Move the clock forward and fire the timers that fall due."""
    freezer.move_to(dt_util.now() + timedelta(**kwargs))
    async_fire_time_changed(hass)
    await settle(hass)


@pytest.mark.asyncio
async def test_freezes_and_then_switches_the_unit_off(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 1
    assert calls["hvac"][0].data["hvac_mode"] == "cool"
    assert calls["hvac"][0].data["entity_id"] == ["climate.test_ac"]

    await advance(hass, freezer, seconds=3)
    assert len(calls["temp"]) == 1
    assert calls["temp"][0].data["temperature"] == 16.0

    await advance(hass, freezer, minutes=11)
    assert len(calls["off"]) == 0

    await advance(hass, freezer, minutes=1, seconds=1)
    assert len(calls["off"]) == 1


@pytest.mark.asyncio
async def test_waits_before_sending_the_freeze_setpoint(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 1
    assert len(calls["temp"]) == 0

    await advance(hass, freezer, seconds=2)
    assert len(calls["temp"]) == 0


@pytest.mark.asyncio
async def test_uses_configured_freeze_settings(hass: HomeAssistant, freezer) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(
        hass, {**DEFAULT_INPUT, "freeze_temperature": 17.5, "freeze_minutes": 5}
    )
    await press_button(hass)

    await advance(hass, freezer, seconds=3)
    assert calls["temp"][0].data["temperature"] == 17.5

    await advance(hass, freezer, minutes=4)
    assert len(calls["off"]) == 0

    await advance(hass, freezer, minutes=1, seconds=1)
    assert len(calls["off"]) == 1


@pytest.mark.asyncio
async def test_raises_the_freeze_setpoint_to_the_unit_minimum(
    hass: HomeAssistant, freezer
) -> None:
    """A unit rejects a setpoint below its min_temp, so it is never sent."""
    hass.states.async_set(
        "climate.test_ac", "off", {"temperature": 20.0, "min_temp": 17}
    )
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await advance(hass, freezer, seconds=3)

    assert calls["temp"][0].data["temperature"] == 17.0


@pytest.mark.asyncio
async def test_keeps_a_freeze_setpoint_above_the_unit_minimum(
    hass: HomeAssistant, freezer
) -> None:
    hass.states.async_set(
        "climate.test_ac", "off", {"temperature": 20.0, "min_temp": 16}
    )
    calls = mock_climate_services(hass)

    await setup_blueprint(hass, {**DEFAULT_INPUT, "freeze_temperature": 18})
    await press_button(hass)
    await advance(hass, freezer, seconds=3)

    assert calls["temp"][0].data["temperature"] == 18.0


@pytest.mark.asyncio
async def test_second_press_while_running_is_ignored(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await advance(hass, freezer, seconds=3)
    await advance(hass, freezer, minutes=1)
    await press_button(hass)

    assert len(calls["hvac"]) == 1

    # The first cycle is not restarted: it still ends on its own schedule.
    await advance(hass, freezer, minutes=11, seconds=1)
    assert len(calls["off"]) == 1


@pytest.mark.asyncio
async def test_minimal_configuration(hass: HomeAssistant, freezer) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "manual_trigger": "input_button.test_clean",
        },
    )
    await press_button(hass)

    await advance(hass, freezer, seconds=3)
    assert calls["temp"][0].data["temperature"] == 16.0

    await advance(hass, freezer, minutes=12, seconds=1)
    assert len(calls["off"]) == 1


@pytest.mark.asyncio
async def test_disables_automations_before_touching_the_unit(
    hass: HomeAssistant,
) -> None:
    calls = mock_climate_services(hass)
    order = []
    hass.bus.async_listen(
        "call_service", callback(lambda e: order.append(e.data["domain"]))
    )

    autos = await setup_blueprint(hass)
    await press_button(hass)

    assert len(autos["off"]) == 1
    assert sorted(autos["off"][0].data["entity_id"]) == [
        "automation.dry_cycle_test_ac",
        "automation.follow_me_test_ac",
    ]
    assert autos["off"][0].data["stop_actions"] is True
    assert len(calls["hvac"]) == 1
    assert order[:2] == ["automation", "climate"]
    assert len(autos["on"]) == 0


@pytest.mark.asyncio
async def test_re_enables_automations_once_the_unit_reports_off(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    autos = await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")
    await advance(hass, freezer, seconds=3)
    await advance(hass, freezer, minutes=12, seconds=1)

    # Switch-off sent, but the unit still reports cool: re-enabling now would
    # let the dry cycle catch our own switch-off.
    assert len(calls["off"]) == 1
    assert len(autos["on"]) == 0

    await report_mode(hass, "off")

    assert len(autos["on"]) == 1
    assert sorted(autos["on"][0].data["entity_id"]) == [
        "automation.dry_cycle_test_ac",
        "automation.follow_me_test_ac",
    ]


@pytest.mark.asyncio
async def test_re_enables_automations_when_the_unit_never_reports_off(
    hass: HomeAssistant, freezer
) -> None:
    mock_climate_services(hass)

    autos = await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")
    await advance(hass, freezer, seconds=3)
    await advance(hass, freezer, minutes=12, seconds=1)
    await advance(hass, freezer, minutes=1)
    assert len(autos["on"]) == 0

    await advance(hass, freezer, minutes=1, seconds=1)
    assert len(autos["on"]) == 1


@pytest.mark.asyncio
async def test_does_not_enable_an_automation_disabled_before_the_cycle(
    hass: HomeAssistant, freezer
) -> None:
    mock_climate_services(hass)
    hass.states.async_set("automation.follow_me_test_ac", "off")

    autos = await setup_blueprint(hass)
    await press_button(hass)

    assert autos["off"][0].data["entity_id"] == ["automation.dry_cycle_test_ac"]

    await report_mode(hass, "cool")
    await advance(hass, freezer, seconds=3)
    await advance(hass, freezer, minutes=12, seconds=1)
    await report_mode(hass, "off")

    assert autos["on"][0].data["entity_id"] == ["automation.dry_cycle_test_ac"]


@pytest.mark.asyncio
async def test_leaves_automations_alone_when_none_are_configured(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    autos = await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "manual_trigger": "input_button.test_clean",
        },
    )
    await press_button(hass)
    await advance(hass, freezer, seconds=3)
    await advance(hass, freezer, minutes=12, seconds=1)

    assert len(calls["off"]) == 1
    assert len(autos["off"]) == 0
    assert len(autos["on"]) == 0

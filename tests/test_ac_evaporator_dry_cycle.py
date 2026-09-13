"""
Tests for ac_evaporator_dry_cycle.yaml

The blueprint dries the indoor unit evaporator with the fan after the AC is
switched off. It emulates the drying stage of the manufacturer self-cleaning
function, which is disabled on multi-split installations.

Note on the drying stage: async_mock_service captures service calls without
updating entity state, so tests that need the cycle to complete must report the
commanded mode back through hass.states.async_set, the way a real integration
would.
"""

import asyncio
import pytest
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_mock_service,
    async_fire_time_changed,
)

BLUEPRINT_PATH = "ac_evaporator_dry_cycle.yaml"

DEFAULT_INPUT = {
    "climate_entity": "climate.test_ac",
    "manual_trigger": "input_button.test_clean",
    "dry_minutes": 15,
    "fan_mode": "high",
    "only_after_cooling": True,
}


async def setup_blueprint(hass: HomeAssistant, config: dict = None) -> None:
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


@pytest.fixture(autouse=True)
def setup_entities(hass: HomeAssistant) -> None:
    hass.states.async_set("climate.test_ac", "cool", {"temperature": 22.0})
    hass.states.async_set("climate.other_1", "off", {})
    hass.states.async_set("climate.other_2", "off", {})
    hass.states.async_set("input_button.test_clean", dt_util.utcnow().isoformat())


def mock_climate_services(hass: HomeAssistant) -> tuple:
    """Mock the three climate services the blueprint uses."""
    return (
        async_mock_service(hass, "climate", "set_hvac_mode"),
        async_mock_service(hass, "climate", "set_fan_mode"),
        async_mock_service(hass, "climate", "turn_off"),
    )


async def settle(hass: HomeAssistant) -> None:
    """Let pending callbacks run.

    async_block_till_done() cannot be used once a cycle is under way: it waits
    for the automation task, which is asleep in a delay, and under the frozen
    clock that timer never fires on its own, so the loop deadlocks.
    """
    for _ in range(30):
        await asyncio.sleep(0)


async def advance(hass: HomeAssistant, freezer, **kwargs) -> None:
    """Move the clock forward and fire the timers that fall due."""
    freezer.move_to(dt_util.now() + timedelta(**kwargs))
    async_fire_time_changed(hass)
    await settle(hass)


async def switch_off(
    hass: HomeAssistant, from_mode: str = "cool", hvac_action: str | None = None
) -> None:
    """Switch the AC off from the given mode, firing the blueprint trigger."""
    attrs = {"temperature": 22.0}
    if hvac_action is not None:
        attrs["hvac_action"] = hvac_action
    hass.states.async_set("climate.test_ac", from_mode, attrs)
    await settle(hass)
    hass.states.async_set("climate.test_ac", "off", {"temperature": 22.0})
    await settle(hass)


@pytest.mark.asyncio
async def test_dries_evaporator_when_ac_switched_off_after_cooling(
    hass: HomeAssistant, freezer
) -> None:
    hvac_calls, fan_calls, off_calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass)

    # Drying starts immediately
    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "fan_only"
    assert len(fan_calls) == 1
    assert fan_calls[0].data["fan_mode"] == "high"
    # The unit is not switched off until the evaporator is dry
    assert len(off_calls) == 0

    # The integration reports the commanded mode back
    hass.states.async_set("climate.test_ac", "fan_only", {})
    await settle(hass)

    await advance(hass, freezer, minutes=15, seconds=1)

    assert len(off_calls) == 1
    assert off_calls[0].data["entity_id"] == ["climate.test_ac"]


@pytest.mark.asyncio
async def test_runs_while_other_indoor_units_are_working(
    hass: HomeAssistant,
) -> None:
    """No multi-split interlock here, unlike the full iClean cycle.

    fan_only runs the indoor fan alone: it requests no refrigerant and imposes
    no mode on the shared outdoor unit. Blocking on busy siblings would mean
    the cycle almost never runs, because a unit is usually switched off while
    other rooms keep working.
    """
    hvac_calls, _, _ = mock_climate_services(hass)

    hass.states.async_set("climate.other_1", "cool", {})
    hass.states.async_set("climate.other_2", "heat", {})

    await setup_blueprint(hass)
    await switch_off(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "fan_only"


@pytest.mark.asyncio
async def test_does_not_run_after_heating(hass: HomeAssistant) -> None:
    """There is no condensate to dry after heating."""
    hvac_calls, _, _ = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass, from_mode="heat")

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_runs_after_heating_when_only_after_cooling_is_disabled(
    hass: HomeAssistant,
) -> None:
    hvac_calls, _, _ = mock_climate_services(hass)

    await setup_blueprint(hass, {**DEFAULT_INPUT, "only_after_cooling": False})
    await switch_off(hass, from_mode="heat")

    assert len(hvac_calls) == 1


@pytest.mark.asyncio
async def test_ignores_transition_from_unavailable(hass: HomeAssistant) -> None:
    """A unit reporting 'off' when it comes back online was never switched off."""
    hvac_calls, _, _ = mock_climate_services(hass)

    await setup_blueprint(hass, {**DEFAULT_INPUT, "only_after_cooling": False})
    await switch_off(hass, from_mode="unavailable")

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_manual_button_starts_cycle_regardless_of_previous_mode(
    hass: HomeAssistant,
) -> None:
    """An explicit request is honoured even when the AC was heating."""
    hvac_calls, _, _ = mock_climate_services(hass)

    hass.states.async_set("climate.test_ac", "heat", {})

    await setup_blueprint(hass)

    hass.states.async_set("input_button.test_clean", dt_util.utcnow().isoformat())
    await settle(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "fan_only"


@pytest.mark.asyncio
async def test_does_not_switch_off_when_user_takes_over_while_drying(
    hass: HomeAssistant, freezer
) -> None:
    _, _, off_calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass)

    # User starts cooling the room again mid-cycle
    hass.states.async_set("climate.test_ac", "cool", {"temperature": 21.0})
    await settle(hass)

    await advance(hass, freezer, minutes=15, seconds=1)

    assert len(off_calls) == 0


@pytest.mark.asyncio
async def test_switches_off_when_unit_went_unavailable_while_drying(
    hass: HomeAssistant, freezer
) -> None:
    """A cloud integration dropping out is not a user taking over."""
    _, _, off_calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass)

    hass.states.async_set("climate.test_ac", "unavailable", {})
    await settle(hass)

    await advance(hass, freezer, minutes=15, seconds=1)

    assert len(off_calls) == 1


@pytest.mark.asyncio
async def test_restart_uses_latest_switch_off(hass: HomeAssistant, freezer) -> None:
    """A second switch off restarts the cycle instead of stacking two of them."""
    hvac_calls, _, off_calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass)

    await advance(hass, freezer, minutes=5)

    # The user switches the AC on and off again: the cycle restarts from here
    await switch_off(hass)
    assert len(hvac_calls) == 2

    hass.states.async_set("climate.test_ac", "fan_only", {})
    await settle(hass)

    # The first cycle would have finished by now, the restarted one has not
    await advance(hass, freezer, minutes=11)
    assert len(off_calls) == 0

    await advance(hass, freezer, minutes=4, seconds=1)
    assert len(off_calls) == 1


@pytest.mark.asyncio
async def test_keeps_current_fan_mode_when_fan_mode_is_empty(
    hass: HomeAssistant,
) -> None:
    hvac_calls, fan_calls, _ = mock_climate_services(hass)

    await setup_blueprint(hass, {**DEFAULT_INPUT, "fan_mode": ""})
    await switch_off(hass)

    assert len(hvac_calls) == 1
    assert len(fan_calls) == 0


@pytest.mark.asyncio
async def test_minimal_configuration(hass: HomeAssistant, freezer) -> None:
    """Only the AC is configured: no manual button, no other indoor units."""
    hvac_calls, fan_calls, off_calls = mock_climate_services(hass)

    await setup_blueprint(hass, {"climate_entity": "climate.test_ac"})
    await switch_off(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "fan_only"
    assert fan_calls[0].data["fan_mode"] == "high"

    hass.states.async_set("climate.test_ac", "fan_only", {})
    await settle(hass)

    # Default drying time is 15 minutes
    await advance(hass, freezer, minutes=14)
    assert len(off_calls) == 0

    await advance(hass, freezer, minutes=1, seconds=1)
    assert len(off_calls) == 1


@pytest.mark.asyncio
async def test_does_not_retrigger_on_its_own_switch_off(
    hass: HomeAssistant, freezer
) -> None:
    """The cycle ends by switching the unit off from fan_only.

    That transition matches the trigger, so without a guard the automation
    would dry the unit again on its own last action, forever.
    """
    hvac_calls, _, off_calls = mock_climate_services(hass)

    await setup_blueprint(hass, {**DEFAULT_INPUT, "only_after_cooling": False})
    await switch_off(hass)
    assert len(hvac_calls) == 1

    hass.states.async_set("climate.test_ac", "fan_only", {})
    await settle(hass)

    await advance(hass, freezer, minutes=15, seconds=1)
    assert len(off_calls) == 1

    # The unit reports the switch off the cycle just commanded
    hass.states.async_set("climate.test_ac", "off", {})
    await settle(hass)

    assert len(hvac_calls) == 1


@pytest.mark.asyncio
async def test_does_not_run_after_heat_cool_spent_heating(
    hass: HomeAssistant,
) -> None:
    """heat_cool runs either way, so the mode alone does not prove cooling."""
    hvac_calls, _, _ = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass, from_mode="heat_cool", hvac_action="heating")

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_runs_after_heat_cool_spent_cooling(hass: HomeAssistant) -> None:
    hvac_calls, _, _ = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass, from_mode="heat_cool", hvac_action="cooling")

    assert len(hvac_calls) == 1


@pytest.mark.asyncio
async def test_runs_after_cooling_even_when_the_unit_was_idle(
    hass: HomeAssistant,
) -> None:
    """Reaching the setpoint does not dry the coil that cooling already wet."""
    hvac_calls, _, _ = mock_climate_services(hass)

    await setup_blueprint(hass)
    await switch_off(hass, from_mode="cool", hvac_action="idle")

    assert len(hvac_calls) == 1

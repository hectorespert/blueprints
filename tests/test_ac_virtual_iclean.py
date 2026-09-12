"""
Tests for ac_virtual_iclean.yaml

Full self-cleaning cycle for indoor units whose manufacturer function is
disabled, as happens with Bosch "I clean" on multi-split installations:

    freeze (cool at the lowest setpoint) → thaw (off) → dry (fan_only) → off

Each stage waits out its time and then checks whether the unit is still the one
it left behind. async_mock_service captures service calls without updating
entity state, so tests report the commanded mode back through
hass.states.async_set, the way a real integration would.
"""

import asyncio
import pytest
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    "other_indoor_units": ["climate.other_1", "climate.other_2"],
    "automations_to_pause": ["automation.follow_me_test_ac"],
    "freeze_temperature": 16,
    "freeze_minutes": 12,
    "thaw_minutes": 8,
    "dry_minutes": 15,
    "freeze_fan_mode": "low",
    "dry_fan_mode": "high",
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
    hass.states.async_set("climate.test_ac", "off", {"temperature": 22.0})
    hass.states.async_set("climate.other_1", "off", {})
    hass.states.async_set("climate.other_2", "off", {})
    hass.states.async_set("input_button.test_clean", dt_util.utcnow().isoformat())


def mock_climate_services(hass: HomeAssistant) -> dict:
    """Mock every climate service the blueprint uses."""
    return {
        "hvac": async_mock_service(hass, "climate", "set_hvac_mode"),
        "temp": async_mock_service(hass, "climate", "set_temperature"),
        "fan": async_mock_service(hass, "climate", "set_fan_mode"),
        "off": async_mock_service(hass, "climate", "turn_off"),
    }


async def settle(hass: HomeAssistant) -> None:
    """Let pending callbacks run.

    async_block_till_done() cannot be used once the cycle is under way: it
    waits for the automation task, which is asleep in a stage delay, and under
    the frozen clock that timer never fires on its own, so the loop deadlocks.
    """
    for _ in range(30):
        await asyncio.sleep(0)


async def press_button(hass: HomeAssistant) -> None:
    hass.states.async_set("input_button.test_clean", dt_util.utcnow().isoformat())
    await settle(hass)


async def report_mode(hass: HomeAssistant, mode: str) -> None:
    """Simulate the integration reporting the commanded mode back."""
    hass.states.async_set("climate.test_ac", mode, {"temperature": 16.0})
    await settle(hass)


async def advance(hass: HomeAssistant, freezer, **kwargs) -> None:
    """Move the clock forward and fire the timers that fall due."""
    freezer.move_to(dt_util.now() + timedelta(**kwargs))
    async_fire_time_changed(hass)
    await settle(hass)


async def advance_freeze(hass: HomeAssistant, freezer, minutes: int) -> None:
    """Step through the freeze stage, which re-checks its siblings once a minute.

    It schedules one 60 second delay at a time, so the clock has to be moved
    once per minute: a single long jump would only complete one iteration.
    """
    for _ in range(minutes):
        await advance(hass, freezer, seconds=61)


@pytest.mark.asyncio
async def test_runs_the_three_stages_and_leaves_the_unit_off(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)

    # Stage 1: freeze
    assert len(calls["hvac"]) == 1
    assert calls["hvac"][0].data["hvac_mode"] == "cool"
    assert calls["temp"][0].data["temperature"] == 16.0
    assert calls["fan"][0].data["fan_mode"] == "low"
    assert len(calls["off"]) == 0

    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 11)
    assert len(calls["off"]) == 0

    # Stage 2: thaw
    await advance_freeze(hass, freezer, 1)
    assert len(calls["off"]) == 1

    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=7)
    assert len(calls["hvac"]) == 1

    # Stage 3: dry
    await advance(hass, freezer, minutes=1, seconds=1)
    assert len(calls["hvac"]) == 2
    assert calls["hvac"][1].data["hvac_mode"] == "fan_only"
    assert calls["fan"][1].data["fan_mode"] == "high"

    await report_mode(hass, "fan_only")
    await advance(hass, freezer, minutes=14)
    assert len(calls["off"]) == 1

    # The unit is left off, like the manufacturer cycle does
    await advance(hass, freezer, minutes=1, seconds=1)
    assert len(calls["off"]) == 2


@pytest.mark.asyncio
async def test_does_not_start_when_another_indoor_unit_is_active(
    hass: HomeAssistant,
) -> None:
    """The freeze stage imposes cooling on the shared outdoor unit."""
    calls = mock_climate_services(hass)

    hass.states.async_set("climate.other_1", "heat", {})

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 0


@pytest.mark.asyncio
async def test_starts_when_other_indoor_units_are_merely_unavailable(
    hass: HomeAssistant,
) -> None:
    calls = mock_climate_services(hass)

    hass.states.async_set("climate.other_2", "unavailable", {})

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 1


@pytest.mark.asyncio
async def test_does_not_start_when_the_unit_is_unavailable(
    hass: HomeAssistant,
) -> None:
    calls = mock_climate_services(hass)

    hass.states.async_set("climate.test_ac", "unavailable", {})

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 0


@pytest.mark.asyncio
async def test_stops_when_user_takes_over_during_freeze(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")

    # User switches the unit to heating mid-freeze
    await report_mode(hass, "heat")
    await advance_freeze(hass, freezer, 12)

    # The cycle unwinds instead of switching the unit off under the user
    assert len(calls["off"]) == 0
    assert len(calls["hvac"]) == 1


@pytest.mark.asyncio
async def test_stops_when_user_takes_over_during_thaw(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 12)
    assert len(calls["off"]) == 1

    # User switches the unit back on while it is thawing
    await report_mode(hass, "cool")
    await advance(hass, freezer, minutes=8, seconds=1)

    # Drying never starts
    assert len(calls["hvac"]) == 1


@pytest.mark.asyncio
async def test_stops_when_user_takes_over_during_dry(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 12)
    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=8, seconds=1)
    assert len(calls["hvac"]) == 2

    # User switches the unit back on while it is drying
    await report_mode(hass, "cool")
    await advance(hass, freezer, minutes=15, seconds=1)

    # Only the thaw switch off happened, the unit is left to the user
    assert len(calls["off"]) == 1


@pytest.mark.asyncio
async def test_second_press_while_running_is_ignored(
    hass: HomeAssistant, freezer
) -> None:
    """mode: single, so a cycle already under way is not restarted."""
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")

    await advance_freeze(hass, freezer, 5)
    await press_button(hass)

    assert len(calls["hvac"]) == 1
    assert len(calls["temp"]) == 1


@pytest.mark.asyncio
async def test_uses_configured_freeze_temperature(hass: HomeAssistant) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(hass, {**DEFAULT_INPUT, "freeze_temperature": 17.5})
    await press_button(hass)

    assert calls["temp"][0].data["temperature"] == 17.5


@pytest.mark.asyncio
async def test_keeps_current_fan_mode_when_fan_modes_are_empty(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)

    await setup_blueprint(
        hass, {**DEFAULT_INPUT, "freeze_fan_mode": "", "dry_fan_mode": ""}
    )
    await press_button(hass)
    assert len(calls["fan"]) == 0

    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 12)
    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=8, seconds=1)

    assert calls["hvac"][1].data["hvac_mode"] == "fan_only"
    assert len(calls["fan"]) == 0


@pytest.mark.asyncio
async def test_minimal_configuration(hass: HomeAssistant, freezer) -> None:
    """Only the AC and its button: no other indoor units, default timings."""
    calls = mock_climate_services(hass)

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "manual_trigger": "input_button.test_clean",
        },
    )
    await press_button(hass)

    assert calls["hvac"][0].data["hvac_mode"] == "cool"
    assert calls["temp"][0].data["temperature"] == 16.0
    assert calls["fan"][0].data["fan_mode"] == "low"

    await report_mode(hass, "cool")

    # Default freeze time is 12 minutes
    await advance_freeze(hass, freezer, 11)
    assert len(calls["off"]) == 0
    await advance_freeze(hass, freezer, 1)
    assert len(calls["off"]) == 1


@pytest.mark.asyncio
async def test_starts_when_another_indoor_unit_only_runs_its_fan(
    hass: HomeAssistant,
) -> None:
    """fan_only claims no mode from the shared outdoor unit.

    Blocking on it would let one unit running the dry cycle stall cleaning in
    another room for the whole drying time.
    """
    calls = mock_climate_services(hass)

    hass.states.async_set("climate.other_1", "fan_only", {})

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 1
    assert calls["hvac"][0].data["hvac_mode"] == "cool"


@pytest.mark.asyncio
async def test_does_not_start_when_another_indoor_unit_is_dehumidifying(
    hass: HomeAssistant,
) -> None:
    """Dehumidifying runs the compressor, so it does claim a mode."""
    calls = mock_climate_services(hass)

    hass.states.async_set("climate.other_2", "dry", {})

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(calls["hvac"]) == 0


@pytest.mark.asyncio
async def test_cuts_the_freeze_short_when_a_sibling_claims_a_mode(
    hass: HomeAssistant, freezer
) -> None:
    """The freeze is the only stage commanding a mode from the outdoor unit.

    It re-checks once a minute rather than waiting the full time blind, and
    carries on to thaw and dry: switching the unit off in stage 2 withdraws
    the conflicting demand, and the coil already holds some condensate.
    """
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")

    await advance_freeze(hass, freezer, 3)
    assert len(calls["off"]) == 0

    # Another room starts heating four minutes into a twelve minute freeze
    hass.states.async_set("climate.other_1", "heat", {})
    await settle(hass)
    await advance_freeze(hass, freezer, 1)

    # Freeze cut short, cycle continues into thaw
    assert len(calls["off"]) == 1

    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=8, seconds=1)
    assert len(calls["hvac"]) == 2
    assert calls["hvac"][1].data["hvac_mode"] == "fan_only"


def mock_automation_services(hass: HomeAssistant) -> dict:
    """Mock the services the cycle uses to silence rival automations.

    Call this *after* setup_blueprint: setting up the automation component
    registers the real turn_on/turn_off services and would replace the mocks.
    """
    return {
        "off": async_mock_service(hass, "automation", "turn_off"),
        "on": async_mock_service(hass, "automation", "turn_on"),
    }


@pytest.mark.asyncio
async def test_disables_rival_automations_and_re_enables_them_at_the_end(
    hass: HomeAssistant, freezer
) -> None:
    calls = mock_climate_services(hass)
    await setup_blueprint(hass)
    autos = mock_automation_services(hass)
    await press_button(hass)

    # Silenced before the AC is touched at all
    assert len(autos["off"]) == 1
    assert autos["off"][0].data["entity_id"] == ["automation.follow_me_test_ac"]
    assert autos["off"][0].data["stop_actions"] is True
    assert len(autos["on"]) == 0

    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 12)
    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=8, seconds=1)
    await report_mode(hass, "fan_only")
    await advance(hass, freezer, minutes=15, seconds=1)

    assert len(calls["off"]) == 2
    assert len(autos["on"]) == 1
    assert autos["on"][0].data["entity_id"] == ["automation.follow_me_test_ac"]


@pytest.mark.asyncio
async def test_re_enables_rival_automations_when_user_takes_over(
    hass: HomeAssistant, freezer
) -> None:
    """The re-enable step sits outside every nested if, so aborts reach it."""
    mock_climate_services(hass)

    await setup_blueprint(hass)
    autos = mock_automation_services(hass)
    await press_button(hass)
    await report_mode(hass, "cool")

    # User switches the unit to heating mid-freeze
    await report_mode(hass, "heat")
    await advance_freeze(hass, freezer, 12)

    assert len(autos["on"]) == 1


@pytest.mark.asyncio
async def test_re_enables_rival_automations_when_freeze_is_cut_short(
    hass: HomeAssistant, freezer
) -> None:
    mock_climate_services(hass)

    await setup_blueprint(hass)
    autos = mock_automation_services(hass)
    await press_button(hass)
    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 3)

    hass.states.async_set("climate.other_1", "heat", {})
    await settle(hass)
    await advance_freeze(hass, freezer, 1)

    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=8, seconds=1)
    await report_mode(hass, "fan_only")
    await advance(hass, freezer, minutes=15, seconds=1)

    assert len(autos["on"]) == 1


@pytest.mark.asyncio
async def test_leaves_automations_alone_when_none_are_configured(
    hass: HomeAssistant,
) -> None:
    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "manual_trigger": "input_button.test_clean",
        },
    )
    autos = mock_automation_services(hass)
    await press_button(hass)

    assert len(autos["off"]) == 0
    assert len(autos["on"]) == 0


@pytest.mark.asyncio
async def test_does_not_disable_automations_when_the_cycle_refuses_to_start(
    hass: HomeAssistant,
) -> None:
    """Conditions are evaluated before the action, so nothing gets silenced."""
    autos = mock_automation_services(hass)

    hass.states.async_set("climate.other_1", "heat", {})

    await setup_blueprint(hass)
    await press_button(hass)

    assert len(autos["off"]) == 0
    assert len(autos["on"]) == 0


@pytest.mark.asyncio
async def test_re_enables_rival_automations_when_a_climate_command_fails(
    hass: HomeAssistant, freezer
) -> None:
    """A failing command must degrade the cycle, not strand the automations.

    Without continue_on_error on the climate steps, an integration that times
    out aborts the script before the re-enable step and leaves Follow Me
    switched off with nothing to switch it back on.
    """
    async_mock_service(
        hass,
        "climate",
        "set_hvac_mode",
        raise_exception=HomeAssistantError("unit did not answer"),
    )
    async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "climate", "set_fan_mode")
    async_mock_service(hass, "climate", "turn_off")

    await setup_blueprint(hass)
    autos = mock_automation_services(hass)
    await press_button(hass)

    assert len(autos["off"]) == 1

    await report_mode(hass, "cool")
    await advance_freeze(hass, freezer, 12)
    await report_mode(hass, "off")
    await advance(hass, freezer, minutes=8, seconds=1)
    await advance(hass, freezer, minutes=15, seconds=1)

    assert len(autos["on"]) == 1


@pytest.mark.asyncio
async def test_stops_when_user_raises_the_freeze_setpoint(
    hass: HomeAssistant, freezer
) -> None:
    """Changing the setpoint claims the unit back without changing the mode."""
    calls = mock_climate_services(hass)

    await setup_blueprint(hass)
    await press_button(hass)
    await report_mode(hass, "cool")

    # User wants it less cold: same hvac mode, different setpoint
    hass.states.async_set("climate.test_ac", "cool", {"temperature": 23.0})
    await settle(hass)
    await advance_freeze(hass, freezer, 12)

    assert len(calls["off"]) == 0

"""
Tests for ac_dehumidify_on_high_humidity.yaml

The blueprint puts the AC in dry mode when humidity rises above a threshold
during a time window, and switches it off when humidity drops below a lower
threshold, the room gets too cold or the window ends.

Note: async_mock_service captures service calls without updating entity state,
so tests that chain several steps report the commanded mode back through
hass.states.async_set, the way a real integration would.
"""

import asyncio
import pytest
from datetime import datetime
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_mock_service,
    async_fire_time_changed,
)

BLUEPRINT_PATH = "ac_dehumidify_on_high_humidity.yaml"

DEFAULT_INPUT = {
    "humidity_sensor": "sensor.test_humidity",
    "climate_entity": "climate.test_ac",
    "start_humidity": 70,
    "stop_humidity": 60,
    "temperature_sensor": "sensor.test_temperature",
    "min_temperature": 18,
    "window_start": "00:00:00",
    "window_end": "08:00:00",
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


async def boot_with_blueprint(hass: HomeAssistant, config: dict = None) -> None:
    """Set the blueprint up while Home Assistant is starting.

    The start trigger only fires for automations enabled during startup, not
    for ones set up on a running instance or reloaded.
    """
    hass.set_state(CoreState.not_running)
    await setup_blueprint(hass, config)
    await hass.async_start()
    await settle(hass)


async def settle(hass: HomeAssistant) -> None:
    """Let pending callbacks run.

    async_block_till_done() cannot be used while the start branch is waiting
    for entities to load: it waits for the automation task, which is blocked on
    a timeout that never fires on its own under the frozen clock.
    """
    for _ in range(30):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def setup_entities(hass: HomeAssistant) -> None:
    hass.states.async_set("climate.test_ac", "off", {"current_temperature": 21.0})
    set_humidity_state(hass, 65)
    set_temperature_state(hass, 21)


@pytest.fixture(autouse=True)
async def detach_time_triggers(hass: HomeAssistant):
    """Turn the automation off after each test.

    Time triggers keep a timer scheduled for their next fire, which the test
    harness reports as a lingering timer. Turning the automation off detaches
    the triggers and cancels those timers.
    """
    yield
    if hass.services.has_service("automation", "turn_off"):
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "all"}, blocking=True
        )


def set_humidity_state(hass: HomeAssistant, value: float) -> None:
    hass.states.async_set(
        "sensor.test_humidity",
        str(value),
        {"device_class": "humidity", "unit_of_measurement": "%"},
    )


async def set_humidity(hass: HomeAssistant, value: float) -> None:
    set_humidity_state(hass, value)
    await hass.async_block_till_done()


def set_temperature_state(hass: HomeAssistant, value: float) -> None:
    hass.states.async_set(
        "sensor.test_temperature",
        str(value),
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )


async def set_temperature(hass: HomeAssistant, value: float) -> None:
    set_temperature_state(hass, value)
    await hass.async_block_till_done()


async def set_climate(
    hass: HomeAssistant, mode: str, current_temperature: float = 21.0
) -> None:
    hass.states.async_set(
        "climate.test_ac", mode, {"current_temperature": current_temperature}
    )
    await hass.async_block_till_done()


def local_time(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(
        2026, 1, 15, hour, minute, second, tzinfo=dt_util.get_default_time_zone()
    )


async def move_clock(hass: HomeAssistant, freezer, when: datetime) -> None:
    """Move the clock and fire the time triggers that fall due."""
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_starts_dry_mode_when_humidity_rises_inside_window(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await setup_blueprint(hass)
    await set_humidity(hass, 75)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"
    assert hvac_calls[0].data["entity_id"] == ["climate.test_ac"]


@pytest.mark.asyncio
async def test_does_not_start_outside_window(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(local_time(12))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await setup_blueprint(hass)
    await set_humidity(hass, 75)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_does_not_start_below_threshold(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await setup_blueprint(hass)
    await set_humidity(hass, 70)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_does_not_take_over_a_running_ac(hass: HomeAssistant, freezer) -> None:
    """A unit already cooling or heating belongs to somebody else."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_climate(hass, "heat")

    await setup_blueprint(hass)
    await set_humidity(hass, 75)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_stops_when_humidity_drops_below_stop_threshold(
    hass: HomeAssistant, freezer
) -> None:
    """The stop path is not limited to the window."""
    freezer.move_to(local_time(12))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_climate(hass, "dry")

    await setup_blueprint(hass)
    await set_humidity(hass, 58)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "off"
    assert hvac_calls[0].data["entity_id"] == ["climate.test_ac"]


@pytest.mark.asyncio
async def test_does_not_stop_inside_hysteresis_band(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_humidity(hass, 75)
    await set_climate(hass, "dry")

    await setup_blueprint(hass)
    await set_humidity(hass, 65)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_does_not_switch_off_other_modes_when_air_is_dry(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_climate(hass, "cool")

    await setup_blueprint(hass)
    await set_humidity(hass, 58)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_stops_dry_mode_when_window_ends(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(local_time(7, 59, 59))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_humidity(hass, 75)
    await set_climate(hass, "dry")

    await setup_blueprint(hass)
    await move_clock(hass, freezer, local_time(8))

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "off"


@pytest.mark.asyncio
async def test_window_end_leaves_other_modes_alone(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(7, 59, 59))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_climate(hass, "cool")

    await setup_blueprint(hass)
    await move_clock(hass, freezer, local_time(8))

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_starts_when_window_opens_with_humidity_already_high(
    hass: HomeAssistant, freezer
) -> None:
    """Humidity crossed the threshold during the day, before the window."""
    freezer.move_to(local_time(23, 59, 59))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_humidity(hass, 75)

    await setup_blueprint(hass)
    assert len(hvac_calls) == 0

    await move_clock(hass, freezer, local_time(0).replace(day=16))

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_window_opening_is_noop_when_air_is_dry(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(23, 59, 59))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await setup_blueprint(hass)
    await move_clock(hass, freezer, local_time(0).replace(day=16))

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_follows_latest_humidity_across_a_night(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(1))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await setup_blueprint(hass)

    await set_humidity(hass, 72)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry"]
    await set_climate(hass, "dry")

    # Still inside the hysteresis band: keeps dehumidifying
    await set_humidity(hass, 66)
    await set_humidity(hass, 61)
    assert len(hvac_calls) == 1

    await set_humidity(hass, 59)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry", "off"]
    await set_climate(hass, "off")

    # Humidity comes back later in the night
    await set_humidity(hass, 68)
    assert len(hvac_calls) == 2
    await set_humidity(hass, 71)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry", "off", "dry"]


@pytest.mark.asyncio
async def test_runs_custom_dehumidify_actions_instead_of_dry_mode(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    script_calls = async_mock_service(hass, "script", "test_dehumidify")

    await setup_blueprint(
        hass,
        {
            **DEFAULT_INPUT,
            "dehumidify_actions": [{"service": "script.test_dehumidify"}],
        },
    )
    await set_humidity(hass, 75)

    assert len(script_calls) == 1
    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_custom_thresholds_and_window_crossing_midnight(
    hass: HomeAssistant, freezer
) -> None:
    config = {
        **DEFAULT_INPUT,
        "start_humidity": 65,
        "stop_humidity": 55,
        "window_start": "22:00:00",
        "window_end": "06:00:00",
    }
    freezer.move_to(local_time(12))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_humidity(hass, 60)

    await setup_blueprint(hass, config)

    # Daytime is outside the window
    await set_humidity(hass, 67)
    assert len(hvac_calls) == 0
    await set_humidity(hass, 60)

    # 23:00 is inside a window that crosses midnight
    freezer.move_to(local_time(23))
    await set_humidity(hass, 67)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry"]
    await set_climate(hass, "dry")

    # 58% is below the default stop threshold but above the custom one
    await set_humidity(hass, 58)
    assert len(hvac_calls) == 1
    await set_humidity(hass, 54)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry", "off"]


@pytest.mark.asyncio
async def test_minimal_configuration(hass: HomeAssistant, freezer) -> None:
    """Only the sensor and the AC: 70/60 % thresholds, 00:00 to 08:00."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await setup_blueprint(
        hass,
        {
            "humidity_sensor": "sensor.test_humidity",
            "climate_entity": "climate.test_ac",
        },
    )

    await set_humidity(hass, 70)
    assert len(hvac_calls) == 0

    await set_humidity(hass, 71)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry"]
    await set_climate(hass, "dry")

    await set_humidity(hass, 60)
    assert len(hvac_calls) == 1

    await set_humidity(hass, 59)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry", "off"]
    await set_climate(hass, "off")

    # 08:00 is the end of the default window
    freezer.move_to(local_time(9))
    await set_humidity(hass, 75)
    assert len(hvac_calls) == 2


@pytest.mark.asyncio
async def test_starts_on_boot_when_humid_inside_window(
    hass: HomeAssistant, freezer
) -> None:
    """Home Assistant was down when the window opened or humidity rose."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_humidity_state(hass, 75)

    await boot_with_blueprint(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_boot_outside_window_is_noop(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(local_time(12))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_humidity_state(hass, 75)

    await boot_with_blueprint(hass)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_boot_is_noop_when_air_is_dry(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")

    await boot_with_blueprint(hass)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_boot_does_not_take_over_a_running_ac(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_humidity_state(hass, 75)
    hass.states.async_set("climate.test_ac", "heat", {})

    await boot_with_blueprint(hass)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_boot_waits_for_the_ac_to_load(hass: HomeAssistant, freezer) -> None:
    """Integrations may still be loading when Home Assistant starts.

    The sensor is already humid, so no threshold is crossed later on: only the
    start branch waiting for the AC can catch this case.
    """
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_humidity_state(hass, 75)
    hass.states.async_set("climate.test_ac", "unavailable", {})

    await boot_with_blueprint(hass)
    assert len(hvac_calls) == 0

    hass.states.async_set("climate.test_ac", "off", {})
    await settle(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_boot_sends_one_command_when_the_sensor_loads_late(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set("climate.test_ac", "unavailable", {})
    hass.states.async_set("sensor.test_humidity", "unavailable", {})

    await boot_with_blueprint(hass)
    assert len(hvac_calls) == 0

    hass.states.async_set("climate.test_ac", "off", {})
    await settle(hass)
    assert len(hvac_calls) == 0

    # The sensor loading also crosses the start threshold. That trigger and the
    # start branch must not both send the command.
    set_humidity_state(hass, 75)
    await settle(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_boot_gives_up_when_entities_never_load(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set("sensor.test_humidity", "unavailable", {})

    await boot_with_blueprint(hass)

    when = local_time(3, 5, 1)
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await settle(hass)
    assert len(hvac_calls) == 0

    # The automation is free again for the regular triggers
    set_humidity_state(hass, 65)
    await settle(hass)
    set_humidity_state(hass, 75)
    await settle(hass)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_does_not_start_when_room_is_too_cold(
    hass: HomeAssistant, freezer
) -> None:
    """Dry mode cools the room further."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_temperature_state(hass, 17.5)

    await setup_blueprint(hass)
    await set_humidity(hass, 75)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_starts_at_exactly_the_minimum_temperature(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_temperature_state(hass, 18)

    await setup_blueprint(hass)
    await set_humidity(hass, 75)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_stops_dry_mode_when_room_gets_too_cold(
    hass: HomeAssistant, freezer
) -> None:
    """Humidity is still high, but the room is getting cold."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_humidity_state(hass, 75)
    await set_climate(hass, "dry")

    await setup_blueprint(hass)
    await set_temperature(hass, 18.5)
    assert len(hvac_calls) == 0

    await set_temperature(hass, 17.5)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "off"
    assert hvac_calls[0].data["entity_id"] == ["climate.test_ac"]


@pytest.mark.asyncio
async def test_cold_room_leaves_other_modes_alone(
    hass: HomeAssistant, freezer
) -> None:
    """Somebody heating a cold room must not be switched off."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    await set_climate(hass, "heat")

    await setup_blueprint(hass)
    await set_temperature(hass, 16)

    assert len(hvac_calls) == 0


@pytest.mark.asyncio
async def test_starts_when_temperature_reading_is_missing(
    hass: HomeAssistant, freezer
) -> None:
    """A dead sensor must not disable dehumidifying altogether."""
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set("sensor.test_temperature", "unavailable", {})

    await setup_blueprint(hass)
    await set_humidity(hass, 75)

    assert len(hvac_calls) == 1
    assert hvac_calls[0].data["hvac_mode"] == "dry"


@pytest.mark.asyncio
async def test_uses_ac_temperature_without_a_sensor(
    hass: HomeAssistant, freezer
) -> None:
    config = {**DEFAULT_INPUT}
    del config["temperature_sensor"]
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    # The dedicated sensor would allow it, but it is not configured
    set_temperature_state(hass, 22)
    await set_climate(hass, "off", current_temperature=17)

    await setup_blueprint(hass, config)
    await set_humidity(hass, 75)
    assert len(hvac_calls) == 0

    # Warmer later in the night, and humidity crosses the threshold again
    await set_climate(hass, "off", current_temperature=19)
    await set_humidity(hass, 65)
    await set_humidity(hass, 75)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry"]

    # The AC's own reading drops below the minimum while drying
    await set_climate(hass, "dry", current_temperature=18.5)
    assert len(hvac_calls) == 1
    await set_climate(hass, "dry", current_temperature=17.5)
    assert [c.data["hvac_mode"] for c in hvac_calls] == ["dry", "off"]


@pytest.mark.asyncio
async def test_boot_does_not_start_when_room_is_too_cold(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to(local_time(3))
    hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    set_humidity_state(hass, 75)
    set_temperature_state(hass, 17)

    await boot_with_blueprint(hass)

    assert len(hvac_calls) == 0

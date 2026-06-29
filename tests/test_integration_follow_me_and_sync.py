"""
Integration test: ac_sync_setpoint_to_input_number + ac_follow_me

Pipeline under test:
  1. User changes the AC setpoint from the remote/dashboard
     → climate.temperature attribute changes
  2. Sync blueprint fires and copies the new setpoint to the input_number helper.
  3. Follow Me blueprint fires (triggered by input_number change) and
     computes the corrected setpoint using the external sensor offset.
"""

import pytest
from datetime import timedelta
from homeassistant.core import HomeAssistant, callback
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service


async def setup_both_blueprints(hass: HomeAssistant) -> None:
    # Register a real input_number.set_value service that updates state
    @callback
    def handle_set_value(call):
        entity_id = call.data.get("entity_id")
        if isinstance(entity_id, list):
            entity_id = entity_id[0]
        hass.states.async_set(
            entity_id,
            str(call.data["value"]),
        )

    hass.services.async_register("input_number", "set_value", handle_set_value)

    ok = await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "use_blueprint": {
                        "path": "ac_sync_setpoint_to_input_number.yaml",
                        "input": {
                            "climate_entity": "climate.test_ac",
                            "target_helper": "input_number.target_temp",
                            "min_change": 0.1,
                            "sync_delay_minutes": 0,
                        },
                    }
                },
                {
                    "use_blueprint": {
                        "path": "ac_follow_me.yaml",
                        "input": {
                            "climate_entity": "climate.test_ac",
                            "external_sensor": "sensor.external_temp",
                            "user_target": "input_number.target_temp",
                            "gain": 0.7,
                            "max_offset": 2.0,
                        },
                    }
                },
            ]
        },
    )
    assert ok
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def setup_entities(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 22.0,
        },
    )
    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set("input_number.target_temp", "22.0")


@pytest.mark.asyncio
async def test_user_remote_change_propagates_through_both_automations(
    hass: HomeAssistant,
) -> None:
    """
    Full pipeline: remote setpoint change → sync → follow me (no mocking input_number).

    Initial state:
      - Climate: cool, internal=22°C, setpoint=22°C
      - External sensor: 24°C (warmer than internal → offset lowers setpoint)
      - input_number: 22°C

    User raises setpoint to 23°C from the remote.
      - Sync sets input_number to 23°C via real service (state updates automatically).
      - Follow Me detects input_number change and computes: 
        offset = (24-22) * 0.7 = 1.4 → setpoint = 23 - 1.4 = 21.6 → 21.5°C
    """
    climate_calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_both_blueprints(hass)

    # Step 1: user changes climate setpoint to 23°C via remote/dashboard
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 23.0,
        },
    )
    await hass.async_block_till_done()

    # Verify input_number was updated by sync blueprint (state now reflects the real service)
    assert hass.states.get("input_number.target_temp").state == "23.0"

    # Verify Follow Me then fired and set the corrected climate temperature
    # offset = (24 - 22) * 0.7 = 1.4 → corrected = 23 - 1.4 = 21.6 → rounded = 21.5
    assert len(climate_calls) == 1
    assert climate_calls[0].data["temperature"] == 21.5


@pytest.mark.asyncio
async def test_sync_does_not_fire_when_change_is_below_threshold(
    hass: HomeAssistant,
) -> None:
    """
    If the remote change is smaller than min_change, sync does not update
    the helper and follow me never fires.

    Only the climate temperature attribute changes (small delta).
    input_number is intentionally not touched so Follow Me is not triggered.
    """
    climate_calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_both_blueprints(hass)

    # Climate setpoint changes by only 0.05°C (below min_change=0.1)
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 22.05,
        },
    )
    await hass.async_block_till_done()

    # Sync skips the update (delta=0.05 < min_change=0.1)
    # → input_number state unchanged
    assert hass.states.get("input_number.target_temp").state == "22.0"
    # Follow Me was never triggered (input_number did not change)
    assert len(climate_calls) == 0

@pytest.mark.asyncio
async def test_sync_respects_stabilization_delay(
    hass: HomeAssistant, freezer
) -> None:
    """
    The sync_delay_minutes parameter delays the sync until the setpoint
    has been stable for that duration. This prevents rapid oscillations.

    Initial: climate.temperature = 22.0, input_number = 22.0

    Step 1: user changes climate to 23.0 at t=0
      → Sync trigger fires but waits (delay=2 minutes)
      → input_number unchanged

    Step 2: at t=1 minute, input_number still 22.0 (delay not yet elapsed)

    Step 3: at t=2+ minutes, delay expires
      → Sync applies the change
      → input_number becomes 23.0
      → Follow Me fires and adjusts the AC
    """
    # Register the real input_number service
    @callback
    def handle_set_value(call):
        entity_id = call.data.get("entity_id")
        if isinstance(entity_id, list):
            entity_id = entity_id[0]
        hass.states.async_set(entity_id, str(call.data["value"]))

    hass.services.async_register("input_number", "set_value", handle_set_value)

    # Setup with a 2-minute delay
    ok = await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "use_blueprint": {
                        "path": "ac_sync_setpoint_to_input_number.yaml",
                        "input": {
                            "climate_entity": "climate.test_ac",
                            "target_helper": "input_number.target_temp",
                            "min_change": 0.1,
                            "sync_delay_minutes": 2,
                        },
                    }
                },
                {
                    "use_blueprint": {
                        "path": "ac_follow_me.yaml",
                        "input": {
                            "climate_entity": "climate.test_ac",
                            "external_sensor": "sensor.external_temp",
                            "user_target": "input_number.target_temp",
                            "gain": 1.0,
                            "max_offset": 2.0,
                        },
                    }
                },
            ]
        },
    )
    assert ok
    await hass.async_block_till_done()

    climate_calls = async_mock_service(hass, "climate", "set_temperature")

    # Step 1: User changes AC setpoint to 23.0
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 23.0,
        },
    )
    await hass.async_block_till_done()

    # input_number should still be 22.0 (sync is waiting for delay)
    assert hass.states.get("input_number.target_temp").state == "22.0"
    # No climate adjustment yet
    assert len(climate_calls) == 0

    # Step 2: Advance time by 1 minute (not enough)
    freezer.move_to(dt_util.now() + timedelta(minutes=1))
    await hass.async_block_till_done()
    # Still waiting
    assert hass.states.get("input_number.target_temp").state == "22.0"
    assert len(climate_calls) == 0

    # Step 3: Advance time by 2+ minutes (delay expires)
    freezer.move_to(dt_util.now() + timedelta(minutes=1, seconds=1))
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    # input_number should now be updated
    assert hass.states.get("input_number.target_temp").state == "23.0"
    # Follow Me should have fired
    # offset = (24 - 22) * 1.0 = 2.0 → setpoint = 23 - 2 = 21.0
    assert len(climate_calls) >= 1
    if len(climate_calls) > 0:
        assert climate_calls[-1].data["temperature"] == 21.0

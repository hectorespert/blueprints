import pytest
from homeassistant.core import HomeAssistant, Context
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

BLUEPRINT_PATH = "ac_sync_setpoint_to_input_number.yaml"


async def setup_blueprint(hass: HomeAssistant, config: dict) -> None:
    ok = await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": BLUEPRINT_PATH,
                    "input": config,
                }
            }
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
            "temperature": 22.0,
        },
    )
    hass.states.async_set("input_number.test_target", "22.0")


@pytest.mark.asyncio
async def test_syncs_setpoint_to_helper_when_delta_reaches_threshold(
    hass: HomeAssistant,
) -> None:
    calls = async_mock_service(hass, "input_number", "set_value")

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "temperature": 23.5,
        },
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["value"] == 23.5


@pytest.mark.asyncio
async def test_does_not_sync_when_delta_is_below_min_change(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "input_number", "set_value")

    hass.states.async_set("input_number.test_target", "23.45")

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "temperature": 23.5,
        },
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_uses_updated_climate_attribute_value(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "input_number", "set_value")

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "temperature": 24.0,
        },
    )
    await hass.async_block_till_done()

    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "temperature": 24.7,
        },
    )
    await hass.async_block_till_done()

    assert len(calls) == 2
    assert calls[0].data["value"] == 24.0
    assert calls[1].data["value"] == 24.7


@pytest.mark.asyncio
async def test_does_not_sync_when_change_caused_by_automation(
    hass: HomeAssistant,
) -> None:
    """
    Setpoint changes caused by an automation (e.g. Follow Me) must not be synced
    back to input_number. Doing so would create a feedback loop that drifts the
    setpoint to extreme values.

    Automation-caused state changes carry a context with parent_id set and
    user_id unset. The blueprint condition must block those.
    """
    calls = async_mock_service(hass, "input_number", "set_value")

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    automation_context = Context(parent_id="follow-me-automation-run-id")
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {"temperature": 20.0},
        context=automation_context,
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_syncs_when_change_has_no_context(
    hass: HomeAssistant,
) -> None:
    """
    Setpoint changes from a physical remote (or any external integration)
    arrive with no parent_id and no user_id. Sync must fire for these.
    """
    calls = async_mock_service(hass, "input_number", "set_value")

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {"temperature": 23.0},
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["value"] == 23.0


@pytest.mark.asyncio
async def test_does_not_sync_when_ac_recovers_from_unavailable(
    hass: HomeAssistant,
) -> None:
    """
    When the AC comes back online from 'unavailable' it reports its last stored
    temperature. That is not a user-initiated setpoint change and must not be
    synced to the input_number helper.
    """
    calls = async_mock_service(hass, "input_number", "set_value")

    # Simulate AC being unavailable (no temperature attribute)
    hass.states.async_set("climate.test_ac", "unavailable", {})

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    # AC comes back online reporting its last stored setpoint
    hass.states.async_set(
        "climate.test_ac",
        "off",
        {"temperature": 25.0},
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_does_not_sync_when_ac_recovers_from_unknown(
    hass: HomeAssistant,
) -> None:
    """
    When the AC transitions from 'unknown' it may report a stale temperature.
    That is not a user-initiated setpoint change and must not be synced.
    """
    calls = async_mock_service(hass, "input_number", "set_value")

    # Simulate AC being in unknown state (no temperature attribute)
    hass.states.async_set("climate.test_ac", "unknown", {})

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    # AC transitions to a known state reporting a temperature
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {"temperature": 24.0},
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_syncs_when_change_has_user_context(
    hass: HomeAssistant,
) -> None:
    """
    Setpoint changes initiated by a user from the HA dashboard carry a
    user_id in their context. Sync must fire for these.
    """
    calls = async_mock_service(hass, "input_number", "set_value")

    await setup_blueprint(
        hass,
        {
            "climate_entity": "climate.test_ac",
            "target_helper": "input_number.test_target",
            "min_change": 0.1,
            "sync_delay_minutes": 0,
        },
    )

    user_context = Context(user_id="dashboard-user-id-123")
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {"temperature": 24.0},
        context=user_context,
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["value"] == 24.0
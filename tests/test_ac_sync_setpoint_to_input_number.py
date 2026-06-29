import pytest
from homeassistant.core import HomeAssistant
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
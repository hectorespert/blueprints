import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

BLUEPRINT_PATH = "ac_follow_me.yaml"

DEFAULT_INPUT = {
    "climate_entity": "climate.test_ac",
    "external_sensor": "sensor.external_temp",
    "user_target": "input_number.target_temp",
    "gain": 1.0,
    "max_offset": 2.0,
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
        "22.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set("input_number.target_temp", "22.0")


@pytest.mark.asyncio
async def test_lowers_setpoint_when_external_is_warmer_than_internal(
    hass: HomeAssistant,
) -> None:
    """External warmer than internal → offset lowers the setpoint (cool mode)."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # offset = (24 - 22) * 1.0 = 2.0; setpoint = 22.0 - 2.0 = 20.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0


@pytest.mark.asyncio
async def test_raises_setpoint_when_external_is_colder_than_internal(
    hass: HomeAssistant,
) -> None:
    """External colder than internal → negative offset raises the setpoint (heat mode)."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    hass.states.async_set(
        "climate.test_ac",
        "heat",
        {
            "hvac_mode": "heat",
            "current_temperature": 22.0,
            "temperature": 22.0,
        },
    )
    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "20.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # offset = (20 - 22) * 1.0 = -2.0; setpoint = 22.0 - (-2.0) = 24.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 24.0


@pytest.mark.asyncio
async def test_gain_scales_the_offset(hass: HomeAssistant) -> None:
    """A lower gain produces a proportionally smaller setpoint correction."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass, {**DEFAULT_INPUT, "gain": 0.5})

    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # offset = (24 - 22) * 0.5 = 1.0; setpoint = 22.0 - 1.0 = 21.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 21.0


@pytest.mark.asyncio
async def test_max_offset_clamps_large_temperature_difference(
    hass: HomeAssistant,
) -> None:
    """A large sensor gap is clamped to max_offset before calculating the setpoint."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass, {**DEFAULT_INPUT, "gain": 1.0, "max_offset": 2.0})

    hass.states.async_set(
        "sensor.external_temp",
        "30.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # raw_offset = (30 - 22) * 1.0 = 8.0 → clamped to 2.0; setpoint = 22.0 - 2.0 = 20.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0


@pytest.mark.asyncio
async def test_setpoint_is_rounded_to_nearest_half_degree(
    hass: HomeAssistant,
) -> None:
    """Final setpoint is always rounded to the nearest 0.5 °C."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "23.3",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # offset = 1.3; corrected = 22 - 1.3 = 20.7 → rounded to nearest 0.5 = 20.5
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.5


@pytest.mark.asyncio
async def test_does_not_act_when_climate_is_unavailable(
    hass: HomeAssistant,
) -> None:
    """No action is taken when the climate entity is unavailable."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    hass.states.async_set("climate.test_ac", "unavailable", {})
    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_does_not_act_when_hvac_mode_is_off(
    hass: HomeAssistant,
) -> None:
    """No action is taken when the HVAC mode is not in the allowed list."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    hass.states.async_set(
        "climate.test_ac",
        "off",
        {
            "hvac_mode": "off",
            "current_temperature": 22.0,
            "temperature": 22.0,
        },
    )
    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_triggers_on_user_target_change(hass: HomeAssistant) -> None:
    """Changing the user target input_number fires the automation."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    # External and internal are equal → offset is 0; only target changes
    await setup_blueprint(hass)

    hass.states.async_set("input_number.target_temp", "24.0")
    await hass.async_block_till_done()

    # offset = (22 - 22) * 1.0 = 0; setpoint = 24.0 - 0 = 24.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 24.0


@pytest.mark.asyncio
async def test_acts_in_heat_cool_mode(hass: HomeAssistant) -> None:
    """Follow Me also adjusts the setpoint when the mode is heat_cool."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    hass.states.async_set(
        "climate.test_ac",
        "heat_cool",
        {
            "hvac_mode": "heat_cool",
            "current_temperature": 22.0,
            "temperature": 22.0,
        },
    )
    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # offset = (24 - 22) * 1.0 = 2.0; setpoint = 22.0 - 2.0 = 20.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0

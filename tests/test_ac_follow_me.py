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


@pytest.mark.asyncio
async def test_triggers_correctly_when_switching_from_unsupported_to_supported_mode(
    hass: HomeAssistant,
) -> None:
    """
    Reproduces the reported issue: AC is in fan mode (unsupported), 
    setpoint changes, then mode switches to cool (supported).
    
    Expected: Follow Me should fire and adjust the setpoint.
    """
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)

    # Step 1: AC is in fan mode (not supported)
    hass.states.async_set(
        "climate.test_ac",
        "fan_only",
        {
            "hvac_mode": "fan_only",
            "current_temperature": 22.0,
            "temperature": 22.0,
        },
    )
    await hass.async_block_till_done()

    # No action expected (fan_only is not in supported modes)
    assert len(calls) == 0

    # Step 2: Setpoint changes while in fan mode
    hass.states.async_set(
        "climate.test_ac",
        "fan_only",
        {
            "hvac_mode": "fan_only",
            "current_temperature": 22.0,
            "temperature": 24.0,  # Changed
        },
    )
    await hass.async_block_till_done()

    # Still no action (fan_only is not supported)
    assert len(calls) == 0

    # Step 3: User switches to cool mode
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 24.0,
        },
    )
    await hass.async_block_till_done()

    # Now the hvac_mode trigger fires AND conditions are met (cool is supported)
    # Follow Me should calculate and apply the setpoint
    # external = 22, internal = 22, offset = 0, target = 22
    # setpoint = 22 - 0 = 22.0
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 22.0


@pytest.mark.asyncio
async def test_mode_switch_with_sensor_offset_present(
    hass: HomeAssistant,
) -> None:
    """
    Realistic scenario: external sensor warmer than internal.
    AC starts in fan → switch to cool → Follow Me should apply offset correction.
    """
    # Initialize with fan mode BEFORE setup to avoid triggering on the initial state
    hass.states.async_set(
        "climate.test_ac",
        "fan_only",
        {
            "hvac_mode": "fan_only",
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

    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)
    await hass.async_block_till_done()

    # No action expected (AC in fan mode, not supported)
    assert len(calls) == 0

    # Switch to cool mode
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 22.0,
        },
    )
    await hass.async_block_till_done()

    # Should apply correction: target=22, offset=(24-22)*1.0=2, setpoint=22-2=20
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0


@pytest.mark.asyncio
async def test_hvac_mode_read_from_state_not_attribute(
    hass: HomeAssistant,
) -> None:
    """
    Verify that hvac_mode is read from the state, not the attribute.
    The attribute 'hvac_modes' (plural) contains the list of available modes.
    The current mode is in the state of the climate entity.
    """
    # Start in fan_only (unsupported) to avoid initial trigger
    hass.states.async_set(
        "climate.test_ac",
        "fan_only",
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "hvac_modes": ["off", "heat", "dry", "cool", "fan_only", "heat_cool"],
        },
    )
    hass.states.async_set(
        "sensor.external_temp",
        "22.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set("input_number.target_temp", "22.0")

    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)
    await hass.async_block_till_done()

    # Should not have triggered (fan_only is not supported)
    assert len(calls) == 0

    climate_state = hass.states.get("climate.test_ac")
    
    # The state should be "fan_only" (current mode)
    assert climate_state.state == "fan_only"
    
    # The attribute hvac_modes contains all available modes
    assert "cool" in climate_state.attributes.get("hvac_modes", [])

    # Now switch to cool mode
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "hvac_modes": ["off", "heat", "dry", "cool", "fan_only", "heat_cool"],
        },
    )
    await hass.async_block_till_done()
    
    # Clear calls from mode change
    calls.clear()
    
    # Now trigger with external sensor change
    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()
    
    # Should have triggered and applied correction
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0  # offset = 2, setpoint = 22 - 2 = 20


@pytest.mark.asyncio
async def test_no_op_when_setpoint_already_correct(
    hass: HomeAssistant,
) -> None:
    """
    When the calculated setpoint equals the current AC setpoint,
    no command should be sent (prevents feedback loops).
    """
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)

    # Set external temp to 24.0, which would calculate: 22.0 - 2.0 = 20.0
    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # First call should happen
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0

    # Now update the AC's current_temperature to 21.0 but keep setpoint at 20.0
    # (simulating AC adjusting its own internal temp after the command)
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 21.0,
            "temperature": 20.0,  # Already set to correct value
        },
    )
    await hass.async_block_till_done()

    # Should NOT trigger a new command because setpoint is already correct
    # (the climate state change triggers but condition blocks it)
    assert len(calls) == 1  # Still just the first call


@pytest.mark.asyncio
async def test_no_feedback_loop_on_continuous_triggers(
    hass: HomeAssistant,
) -> None:
    """
    Reproduces the original issue: continuous temperature drops.
    Verifies that the new condition prevents feedback loops.
    """
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)

    # Simulate external temp change that requires setpoint correction
    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # First execution should happen
    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0

    # Simulate AC's internal sensor adjusting temperature
    # (this would trigger the automation again in the original bug)
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 21.0,  # Internal temp changed
            "temperature": 20.0,  # But setpoint is already at target
        },
    )
    await hass.async_block_till_done()

    # Should NOT make another call because final_setpoint (20.0) == current_setpoint (20.0)
    assert len(calls) == 1

    # Simulate another internal temp update
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 20.5,
            "temperature": 20.0,
        },
    )
    await hass.async_block_till_done()

    # Still should be just 1 call (no feedback loop)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_recalculates_when_setpoint_differs(
    hass: HomeAssistant,
) -> None:
    """
    Verifies that the automation DOES send a command when the calculated
    setpoint differs from the current AC setpoint.
    """
    calls = async_mock_service(hass, "climate", "set_temperature")

    await setup_blueprint(hass)

    # Initial external temp: calculate setpoint = 20.0
    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["temperature"] == 20.0

    # Now AC's setpoint is manually changed to 21.0 (user or other automation)
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": 22.0,
            "temperature": 21.0,  # Different from calculated (20.0)
        },
    )
    await hass.async_block_till_done()

    # Now trigger with a new sensor value
    hass.states.async_set(
        "sensor.external_temp",
        "25.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    # New setpoint: offset = (25-22)*1.0 = 3, clamped to 2, setpoint = 22-2 = 20.0
    # Current setpoint is 21.0, so should trigger
    assert len(calls) == 2
    assert calls[1].data["temperature"] == 20.0


@pytest.mark.asyncio
async def test_no_op_when_setpoint_change_is_below_hysteresis(
    hass: HomeAssistant,
) -> None:
    """No command when the calculated change is smaller than the hysteresis threshold."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    # current AC setpoint = 22.0; with external=22.5, offset=0.5, final=21.5
    # |21.5 - 22.0| = 0.5, which is strictly below hysteresis=1.0 → no action
    await setup_blueprint(hass, {**DEFAULT_INPUT, "hysteresis": 1.0})

    hass.states.async_set(
        "sensor.external_temp",
        "22.5",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_acts_when_setpoint_change_meets_hysteresis_threshold(
    hass: HomeAssistant,
) -> None:
    """Command is sent when the calculated change equals the hysteresis threshold."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    # current AC setpoint = 22.0; with external=23.0, offset=1.0, final=21.0
    # |21.0 - 22.0| = 1.0, which exactly equals hysteresis=1.0 → action
    await setup_blueprint(hass, {**DEFAULT_INPUT, "hysteresis": 1.0})

    hass.states.async_set(
        "sensor.external_temp",
        "23.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["temperature"] == 21.0


@pytest.mark.asyncio
async def test_hysteresis_zero_allows_any_change(
    hass: HomeAssistant,
) -> None:
    """Setting hysteresis to 0.0 allows any non-zero setpoint change to trigger."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    # current AC setpoint = 22.0; with external=22.5, offset=0.5, final=21.5
    # hysteresis=0.0 means any non-zero change triggers: |21.5 - 22.0| = 0.5 > 0.0 → action
    await setup_blueprint(hass, {**DEFAULT_INPUT, "hysteresis": 0.0})

    hass.states.async_set(
        "sensor.external_temp",
        "22.5",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["temperature"] == 21.5


@pytest.mark.asyncio
async def test_default_hysteresis_blocks_same_setpoint(
    hass: HomeAssistant,
) -> None:
    """Default hysteresis (0.5) suppresses an update when the setpoint would not change."""
    calls = async_mock_service(hass, "climate", "set_temperature")

    # external == internal → offset = 0, final = target = 22.0 == current → blocked
    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "22.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_diagnostics_helper_is_optional(hass: HomeAssistant) -> None:
    """No diagnostics service call is made when the optional helper is not configured."""
    climate_calls = async_mock_service(hass, "climate", "set_temperature")
    diagnostics_calls = async_mock_service(hass, "input_text", "set_value")

    await setup_blueprint(hass)

    hass.states.async_set(
        "sensor.external_temp",
        "24.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(climate_calls) == 1
    assert climate_calls[0].data["temperature"] == 20.0
    assert len(diagnostics_calls) == 0


@pytest.mark.asyncio
async def test_diagnostics_helper_logs_last_calculation_even_without_action(
    hass: HomeAssistant,
) -> None:
    """Diagnostics store the last calculation even when hysteresis blocks the command."""
    climate_calls = async_mock_service(hass, "climate", "set_temperature")
    diagnostics_calls = async_mock_service(hass, "input_text", "set_value")

    hass.states.async_set("input_text.follow_me_debug", "")

    await setup_blueprint(
        hass,
        {
            **DEFAULT_INPUT,
            "diagnostics_helper": "input_text.follow_me_debug",
            "hysteresis": 1.0,
        },
    )

    hass.states.async_set(
        "sensor.external_temp",
        "22.5",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(climate_calls) == 0
    assert len(diagnostics_calls) == 1

    diagnostics_message = diagnostics_calls[0].data["value"]
    assert "m=cool" in diagnostics_message
    assert "e=22.5" in diagnostics_message
    assert "i=22.0" in diagnostics_message
    assert "t=22.0" in diagnostics_message
    assert "o=0.5" in diagnostics_message
    assert "f=21.5" in diagnostics_message
    assert "c=22.0" in diagnostics_message
    assert "a=False" in diagnostics_message


@pytest.mark.parametrize(
    "target,external,internal,current_sp,gain,max_offset,expected",
    [
        # (target, external, internal, current_setpoint, gain, max_offset, expected_setpoint)
        pytest.param(
            25.0,
            24.3,
            22.0,
            22.0,
            0.7,
            2.0,
            23.5,
            id="target_25_ext_24_3_int_22_gain_0_7",
        ),
        pytest.param(
            25.0,
            24.3,
            25.5,
            25.0,
            0.7,
            2.0,
            26.0,
            id="target_25_ext_24_3_int_25_5_gain_0_7",
        ),
        pytest.param(
            22.0,
            20.0,
            22.0,
            22.0,
            1.0,
            2.0,
            24.0,
            id="target_22_ext_20_negative_offset",
        ),
        pytest.param(
            23.0,
            23.0,
            22.0,
            22.0,
            0.5,
            2.0,
            22.5,
            id="target_23_ext_23_gain_0_5",
        ),
        pytest.param(
            20.0,
            26.0,
            22.0,
            22.0,
            1.0,
            1.5,
            18.5,
            id="target_20_ext_26_clamped_to_1_5",
        ),
    ],
)
@pytest.mark.asyncio
async def test_follow_me_scenarios(
    hass: HomeAssistant,
    target: float,
    external: float,
    internal: float,
    current_sp: float,
    gain: float,
    max_offset: float,
    expected: float,
) -> None:
    """
    Parametrized test covering various Follow Me scenarios:
    - Different comfort targets (20-25°C)
    - Various external/internal temperature differences
    - Different gain values (soft, recommended, direct)
    - Offset clamping in effect
    """
    calls = async_mock_service(hass, "climate", "set_temperature")

    hass.states.async_set("input_number.target_temp", str(target))
    hass.states.async_set(
        "climate.test_ac",
        "cool",
        {
            "hvac_mode": "cool",
            "current_temperature": internal,
            "temperature": current_sp,
        },
    )

    await setup_blueprint(hass, {**DEFAULT_INPUT, "gain": gain, "max_offset": max_offset})

    hass.states.async_set(
        "sensor.external_temp",
        str(external),
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["temperature"] == expected

# HomeAssistant Blueprints

Home Assistant blueprints collection.

## Available Blueprints

### 1. AC Sync Setpoint to Input Number

Synchronizes the climate target temperature with an `input_number` helper. This allows remote/dashboard setpoint changes to become the base target used by the Follow Me automation.

**Use case:** When you want the Follow Me system to respect manual temperature adjustments from your AC remote or dashboard.

**Features:**
- Syncs climate setpoint to an input_number helper
- Configurable minimum change threshold to avoid unnecessary updates
- Optional stabilization delay to prevent oscillations
- Works as a bridge between physical AC remote and virtual Follow Me system

**Installation:**

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fhectorespert%2Fblueprints%2Fmain%2Fblueprints%2Fac_sync_setpoint_to_input_number.yaml)

Or manually: `automations/blueprints/ac_sync_setpoint_to_input_number.yaml`

---

### 2. Virtual Follow Me AC v1

Basic Follow Me system that adjusts AC setpoint based on the difference between an external sensor (user's actual location) and the AC's internal sensor. This compensates for spatial temperature variations.

**Use case:** Create a "follow me" experience where the AC adjusts to your actual comfort level, not just the room's temperature.

**Formula:**
```
setpoint = user_target - (external_temp - internal_temp) * gain
```

**Features:**
- Proportional offset calculation with configurable gain
- Offset clamping to prevent overcorrection
- Automatic rounding to 0.5°C increments
- Hysteresis threshold to prevent oscillations near setpoint
- Support for cool, heat, and heat_cool modes
- Works with external sensors and AC's internal temperature probe

**Installation:**

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fhectorespert%2Fblueprints%2Fmain%2Fblueprints%2Fac_follow_me.yaml)

Or manually: `automations/blueprints/ac_follow_me.yaml`

---

### 3. AC Evaporator Dry Cycle

Runs the indoor fan for a while after the AC is switched off, so the evaporator
dries instead of staying wet. This is the drying stage of the manufacturer
self-cleaning function, rebuilt as an automation.

**Use case:** manufacturers disable self-cleaning on multi-split installations.
Bosch Climate 3000i, for instance, lists *Self-cleaning (I clean)* among the
functions turned off when the indoor unit shares an outdoor unit, together with
ECO and GEAR, Silent Mode, manual operation, refrigerant leak detection and
1 W standby.

**Features:**
- Triggered when the AC is switched off, by a button, or both
- Safe to run on a multi-split while other rooms are working: `fan_only` runs
  the indoor fan alone, requesting no refrigerant and imposing no mode on the
  shared outdoor unit
- Skips the cycle after heating, where there is no condensate to dry
- Leaves the unit alone if somebody takes control while it is drying
- Only uses `fan_only` and `off`, so it never collides with Follow Me

**Installation:**

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fhectorespert%2Fblueprints%2Fmain%2Fblueprints%2Fac_evaporator_dry_cycle.yaml)

Or manually: `automations/blueprints/ac_evaporator_dry_cycle.yaml`

---

### 4. AC Virtual iClean

Full self-cleaning cycle, driven from a button: freeze the evaporator at the
lowest setpoint with a slow fan, stop so the ice thaws and washes dirt down the
drain, then dry the coil at full fan speed and leave the unit off.

**Use case:** a deep clean on installations where the manufacturer function is
unavailable.

**Cycle:**
```
freeze (cool @ min setpoint, slow fan) → thaw (off) → dry (fan_only, fast fan) → off
```

**Features:**
- Manual only: the cycle takes the unit out of service for around 35 minutes
- Multi-split interlock: refuses to start while another indoor unit claims a
  mode (cooling, heating, dehumidifying, auto), because the freeze stage
  imposes cooling on the shared outdoor unit. A sibling merely running its fan
  does not block it
- The freeze stage re-checks its siblings once a minute and cuts itself short
  if another room claims a mode meanwhile, then carries on to thaw and dry
- Disables rival automations (Follow Me, schedules) while it runs and
  re-enables them on every path out of the cycle
- Unwinds cleanly at any stage boundary if somebody takes control
- `mode: single`, so pressing the button twice does not stack two cycles

**Limitations, worth reading before use:**
- **Frosting is not guaranteed.** The compressor is shared between indoor
  units and its capacity is split, so the freeze stage is milder than the
  manufacturer one.
- **No disinfection stage.** Heating the evaporator to the temperature the
  manufacturer cycle reaches is not possible through climate services.
- **Keep `freeze_minutes` moderate.** A long freeze on a unit with a slow drain
  can overflow the condensate tray.

If you only care about preventing mould and stale smells, the Evaporator Dry
Cycle blueprint gets most of the benefit with none of these caveats.

**Pairing with Follow Me:** the freeze stage drives the setpoint on purpose, so
list the Follow Me automation for this unit under **Automations to disable
during the cycle**. iClean switches them off before it touches the AC and back
on when it finishes. This works for any automation that drives the AC, not just
ones built from these blueprints.

The re-enable step sits at the top level of the sequence, so it is reached on
every path inside the cycle: a normal finish, a freeze cut short by a busy
sibling, or you taking over the unit. Every climate command carries
`continue_on_error`, so a unit rejecting a mode or an integration timing out
degrades the cycle rather than aborting it with the automations still off.

**The one gap:** if Home Assistant restarts mid-cycle, the sequence never
reaches the re-enable step and those automations stay disabled until you turn
them back on. They appear greyed out in the UI, so it is visible. There is
deliberately no automatic recovery on startup, because that would also
re-enable automations you had disabled by hand.

**Installation:**

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fhectorespert%2Fblueprints%2Fmain%2Fblueprints%2Fac_virtual_iclean.yaml)

Or manually: `automations/blueprints/ac_virtual_iclean.yaml`

---

## Recommended Setup

For a complete Follow Me system:

1. **First:** Import the "AC Sync Setpoint to Input Number" blueprint
2. **Then:** Import the "Virtual Follow Me AC v1" blueprint
3. **Create:** An `input_number` helper for your target temperature
4. **Configure:** Both blueprints to use the same `input_number` as the connection point

This creates a pipeline: `Remote/Dashboard → Sync → Input Number → Follow Me → AC Adjustment`

### Multi-split installations

One outdoor unit with several indoor units needs **one automation per indoor
unit**, for every blueprint you use.

Only **AC Virtual iClean** has an **Other indoor units** input, because its
freeze stage puts the unit into cooling and that imposes a mode on the shared
outdoor unit. Fill it with the remaining `climate` entities. The cycle then
refuses to start while any of them is cooling, heating, dehumidifying or in
auto, and the freeze stage keeps re-checking once a minute so a room that
starts heating mid-cycle cuts the freeze short instead of fighting it.

**AC Evaporator Dry Cycle** has no such input on purpose. It only uses
`fan_only`, which runs the indoor fan without requesting refrigerant, so it
cannot conflict with another room. Gating it on idle siblings would mean it
almost never ran: a unit is normally switched off while the rest of the house
keeps working.

---

## Roadmap: v2 Improvements

We are planning significant enhancements to improve stability, user experience, and energy efficiency:

### **Phase 1: Core Stability (v2.0)**
- [x] **Hysteresis Anti-Jitter** - Prevent oscillations when temperature fluctuates near setpoint
- [ ] **Temporal Stabilization** - Wait for sensor reading stability before applying changes
- [ ] **Multiple External Sensors** - Average temperature from multiple zones/rooms
- [ ] **Advanced Rate Limiting** - Limit max temperature change per hour (e.g., 3°C/h)
- [ ] **Robust Data Validation** - Validate all sensor inputs before processing
- [ ] **Equipment Limits** - Respect min/max temperature constraints of the AC unit

### **Phase 2: Diagnostics & Precision (v2.1)**
- [ ] **Built-in Diagnostics** - Log last calculation to `input_text` for debugging
- [ ] **Dynamic Step Rounding** - Auto-detect AC's temperature step precision

### **Implementation Timeline**

| Priority | Phase | Effort | Status |
|----------|-------|--------|--------|
| 🔴 High | Core Stability | ~7h | 🔄 In Progress |
| 🟡 Medium | Diagnostics | ~2h | 📋 Planned |

### **Backward Compatibility**

All v2 improvements will be **optional** with defaults matching v1 behavior:
- New parameters will have sensible defaults
- Existing setups will continue to work unchanged
- No breaking changes to blueprints API

---

## Tests

Run tests with pip in a local virtual environment:

1. Create and activate a virtual environment.
2. Install dependencies from requirements-test.txt.
3. Run pytest.

Example:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
pytest -q
```

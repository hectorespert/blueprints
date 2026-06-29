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

## Recommended Setup

For a complete Follow Me system:

1. **First:** Import the "AC Sync Setpoint to Input Number" blueprint
2. **Then:** Import the "Virtual Follow Me AC v1" blueprint
3. **Create:** An `input_number` helper for your target temperature
4. **Configure:** Both blueprints to use the same `input_number` as the connection point

This creates a pipeline: `Remote/Dashboard → Sync → Input Number → Follow Me → AC Adjustment`

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

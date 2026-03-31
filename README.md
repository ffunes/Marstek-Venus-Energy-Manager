# Marstek Venus Energy Manager for Home Assistant


The **Marstek Venus Energy Manager** is a comprehensive Home Assistant integration designed to monitor and control Marstek Venus E series batteries (v2 and v3) and Venus D and Venus A series batteries via Modbus TCP. It provides advanced energy management features including predictive grid charging, customizable time slots for discharge control, and device load exclusion logic.

> [!CAUTION]
> **LIABILITY DISCLAIMER:**
> This software is provided "as is", without warranty of any kind, express or implied. By using this integration, you acknowledge and agree that:
> 1.  **Use is at your own risk.** The developer(s) assume **NO RESPONSIBILITY** or **LIABILITY** for any damage, loss, or harm resulting from the use of this software.
> 2.  This includes, but is not limited to: damage to your batteries, inverters, home appliances, electrical system, fire, financial loss, or personal injury.
> 3.  You are solely responsible for ensuring that your hardware is compatible and safely configured.
> 4.  Interacting with high-voltage battery systems and Modbus registers always carries inherent risks. Incorrect settings or commands could potentially damage hardware.
>
> **If you do not agree to these terms, DO NOT install or use this integration.**

## Support

If you find this integration useful, you can support my work:

<a href="https://buymeacoffee.com/ffunes" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="40" width="145" ></a>


## Key Features

### 1. Core Functionality: Dynamic Power Control
This is the primary operating mode of the integration, designed to maximize self-consumption.
*   **Zero Export/Import (PD Controller)**: A built-in Proportional-Derivative controller continuously monitors your grid meter (e.g., Shelly EM) and adjusts battery charge/discharge rates to keep grid exchange close to your configured target (0W by default, configurable per time slot).
*   **Oscillation Prevention**: Advanced logic with "Deadband" and "Derivative Gain" prevents the battery from wildly swinging between charge/discharge during sudden load spikes (like a coffee machine toggling on/off).
*   **Hardware Control**:
    *   Set maximum charge and discharge power limits.
    *   Configure minimum and maximum SOC operational limits.
    *   Force charge or discharge modes manually.
*   **Battery load sharing**: Intelligent battery selection that uses the minimum number of batteries needed to keep each one operating in its optimal efficiency zone. Based on the Venus efficiency curve, batteries activate when total power exceeds 60% of combined capacity (peak efficiency ~91% at 1000-1500W). Features:
    *   **Discharge priority**: Highest SOC first (drain fullest battery).
    *   **Charge priority**: Lowest SOC first (fill emptiest battery).
    *   **SOC hysteresis (5%)**: Active battery stays selected until another exceeds it by 5% SOC.
    *   **Energy hysteresis (2.5 kWh)**: Tiebreaker uses lifetime energy with 2.5 kWh advantage for active battery, balancing long-term wear.
    *   **Power hysteresis (±100W)**: Activates 2nd battery at 60% capacity threshold, deactivates at 50% to prevent ping-pong with fluctuating loads.
    *   Applies to all modes: normal PD control, solar charging, and predictive grid charging.

### 2. Advanced: Predictive Grid Charging
**Optional** feature that operates independently of normal usage to ensure energy security.
*   **Smart Energy Balance**: The system intelligently decides *if* and *how much* to charge from the grid overnight based on:
    1.  **Usable Energy**: Current battery level above discharge cutoff.
    2.  **Solar Forecast**: Expected production for tomorrow (via Solcast/Forecast.Solar).
    3.  **Consumption Forecast**: 7-day rolling average of your actual home usage.
*   **The Logic**: If `(Usable Battery + Solar Forecast) < Expected Consumption`, it charges from the grid during cheap overnight hours to cover *exactly* the deficit.
*   **Cost Saving**: If there is a surplus, it stays idle, saving you money by not buying unnecessary grid power.

### 3. Additional Management Features
*   **Real-time Monitoring**: View battery SOC, power flow, voltage, current, temperature, and cell-level health.
*   **Multi-Battery Support**: Seamlessly manage up to 4 batteries as a single aggregated system.
*   **Discharge Time Slots**: Allow the battery to discharge during specific times (e.g., peak grid rates). Each slot supports configurable **target grid power**, **minimum charge power**, and **minimum discharge power**.
*   **Weekly Full Charge**: Option to force a full charge once a week for cell balancing.
*   **Solar-Aware Charge Delay**: Delays morning charging (or the weekly 100% charge) while solar production can still cover the required energy. Uses a sinusoidal solar model and a stored nightly forecast so the battery only starts charging from grid when solar won't be sufficient.
*   **Capacity Protection (Peak Shaving)**: Conserves battery energy when SOC drops below a configurable threshold. Instead of covering all household consumption, the battery only discharges to offset loads that exceed a configurable peak power limit.
*   **Load Exclusion**: "Hide" specific heavy loads (like EV chargers) from the battery to prevent rapid draining.

## Requirements

*   **Hardware:** 
    *   Marstek Venus E v2/v3, Venus A or Venus D Battery.
    *   **Modbus to WiFi Converter:** A device to bridge the battery's RS485 Modbus to your network via TCP. (e.g., **Elfin-EW11**).
    *   **Grid Consumption Sensor:** A Home Assistant sensor tracking your home's total grid consumption (e.g., from a Shelly EM3, Neural, or smart meter integration).
*   **Network:** The battery must be on the same network as Home Assistant or reachable via IP.
*   **Home Assistant:** Recent version (tested on 2024.x).
*   **(Optional) Solar Forecast:** A sensor providing tomorrow's solar forecast (in kWh) is required for the Predictive Grid Charging feature.

## Installation

1.  **HACS (Recommended)**:
    *   Add this repository as a **Custom Repository** in HACS:
        *   Url: `https://github.com/ffunes/Marstek-Venus-Energy-Manager`
        *   Category: **Integration**
    *   Search for "Marstek Venus Energy Manager" and install.
    *   Restart Home Assistant.

2.  **Manual**:
    *   Download the release zip.
    *   Extract the `marstek_venus_energy_manager` folder.
    *   Copy it to your Home Assistant `custom_components` directory.
    *   Restart Home Assistant.

## Configuration Walkthrough

This integration is configured entirely via the Home Assistant UI.

### 1. Initial Setup
*   Go to **Settings** > **Devices & Services**.
*   Click **+ ADD INTEGRATION**.
*   Search for **Marstek Venus Energy Manager**.

### 2. Main Household Sensor
*   **Consumption Sensor**: Select the sensor that measures your home's total grid consumption (W or kW). This is critical for the integration to calculate load and managing battery behavior relative to the grid.
*   **Solar Forecast Sensor** *(Optional)*: Select the sensor that provides tomorrow's solar energy production estimate (in **kWh** or **Wh**). Configuring it here makes it available to both the **Predictive Grid Charging** (step 6) and **Charge Delay** (step 8) features. You can skip this now and configure it later in those individual steps if preferred.

### 3. Battery Setup
*   **Number of Batteries**: Select how many Marstek Venus units you have (1-4).
*   **Battery Configuration** (Repeated for each battery):
    *   **Name**: Give your battery a unique name (e.g., "Venus Battery 1").
    *   **Host**: The IP address of the battery (or the Modbus-TCP bridge/stick connected to it).
    *   **Port**: The Modbus TCP port (default is `502`).
    *   **Version**: Select your battery model (`v1/v2` or `v3`).
    *   **Max Charge/Discharge Power**: Select the rated power of your setup (e.g., `2500W`).
        > [!CAUTION]
        > **Safety Warning:** Only use the **2500W** mode if you are sure that your domestic installation can withstand such power.
    *   **SOC Limits**:
        *   **Max SOC**: Stop charging at this percentage (default 100%).
        *   **Min SOC**: Stop discharging at this percentage (default 12%).
    *   **Charge Hysteresis**: (Optional) Prevent rapid cycling near the charge limit.

### 4. Time Slots (Optional)
You can define specific time periods where the battery is **allowed to discharge**. This is useful for saving battery power for evening peaks or overnight usage. Each time slot also supports advanced per-slot controller parameters.
*   **Enable**: Check "Configure time slots".
*   **Add Slot**:
    *   **Start/End Time**: Define the window (e.g., `14:00` to `18:00`).
    *   **Days**: Select applicable days of the week.
    *   **Apply to charge**: (Advanced) If checked, this slot also restricts charging.
    *   **Target Grid Power** *(New in v1.1.0)*: The grid power level the controller regulates toward during this slot. Default: `0W` (zero grid flow). Set to negative values (e.g., `-150W`) to intentionally maintain slight export, or positive values to allow slight import. Useful for tariff optimization when feed-in is more valuable than self-consumption. Range: `-500W` to `+500W`.

### 5. Excluded Devices (Optional)
This feature allows you to "mask" high-power devices so the battery doesn't try to cover their load. For example, if you turn on a 7kW car charger, you might not want your 2.5kW battery to drain itself instantly.
*   **Enable**: Check "Configure excluded devices".
*   **Add Device**:
    *   **Power Sensor**: The entity measuring the power of the heavy load (e.g., `sensor.wallbox_power`).
    *   **Included in Consumption**: Check this if your *Main Household Sensor* (step 2) already sees this load. Uncheck if it's on a separate circuit not monitored by the main sensor.
    *   **Allow Solar Surplus**: If checked, the battery will not charge to compensate for this device's consumption when the system is running on solar surplus.

### 6. Predictive Charging (Optional)
Automatically charge the battery from the grid when tomorrow's solar forecast is insufficient to cover expected consumption. Three modes are available:

#### Mode A — Time Slot
Charges during a fixed time window (e.g. overnight off-peak hours).
*   **Enable**: Check "Configure predictive charging" and select **Time Slot**.
*   **Settings**:
    *   **Time Window**: When to charge from the grid (e.g., `02:00` – `05:00`).
    *   **Solar Forecast Sensor** *(Optional)*: Sensor providing the next day's solar production in **kWh** (e.g. Solcast, Forecast.Solar). Leave empty if you have no solar panels — the system will charge whenever battery energy alone is insufficient.
    *   **Max Contracted Power**: Your grid connection limit (W). The system ensures charging + house load doesn't trip your main breaker.

> [!NOTE]
> **Notification**: A Home Assistant notification is sent **one hour before** the configured start time with the calculated energy balance and the charging decision. Use the **Override Predictive Charging** switch to cancel if needed.

#### Mode B — Dynamic Pricing
Instead of a fixed window, the system evaluates electricity prices for the day and automatically selects the **cheapest available hours** to cover the energy deficit.

*   **Enable**: Check "Configure predictive charging" and select **Dynamic Pricing**.
*   **Settings**:
    *   **Price integration**: Choose your electricity price provider:
        *   **Nordpool / Energi Data Service** (HACS Nordpool integration - https://github.com/custom-components/nordpool) — prices in **ct/kWh**. Supports 15-minute and hourly slots.
        *   **PVPC (Spain / ESIOS REE)** (https://github.com/oscarrgarciia/HA-PVPC-Updated) — prices in **€/kWh**.
        *   **CKW (Switzerland)** (https://github.com/trolli-ch/hass-ckw-dynamic-pricing) — prices in **Rp/kWh** (Swiss Rappen).
    *   **Price sensor**: The HA sensor entity that exposes the price data from the selected integration.
    *   **Maximum price threshold** *(Optional)*: Slots above this price are excluded even if they are the cheapest available. Use the same unit as the sensor (`ct/kWh` for Nordpool, `€/kWh` for PVPC, `Rp/kWh` for CKW). Leave empty to allow all slots.
    *   **Solar Forecast Sensor** *(Optional)*: Same as Time Slot mode — leave empty if no solar panels.
    *   **Max Contracted Power**: Same as Time Slot mode.

*   **How it works**:
    1.  Every day at **00:05** the system calculates the energy deficit: `usable battery energy + solar forecast − expected consumption`.
    2.  If a deficit exists, it picks the cheapest hours from the price data to cover it, respecting the max price threshold.
    3.  If no deficit exists, it still selects the equivalent cheapest hours as an **informational reference** (no grid charging will activate).
    4.  If HA or the integration restarts after 00:05 and no evaluation has been done yet, a **startup evaluation** runs automatically (15 s after startup) using the remaining slots of the current day only — tomorrow's slots are reserved for the next 00:05 run.
    5.  If price data is not yet available at 00:05, the system retries every 15 minutes until 01:00.

> [!NOTE]
> **Notification**: Sent at **00:05** (or on startup) with the full energy balance, selected hours, average price, and estimated cost. When no charging is needed, the notification is clearly labelled as informational. Use the **Override Predictive Charging** switch to cancel an active charge session.

#### Mode C — Automation Slot (External Price Sensor)
Instead of the integration deciding when to charge, an **external HA automation controls the charging slot in real time**. The integration exposes a switch (`Automation Charging Active`) and a time entity (`Automation Charging End Time`); any automation that sets these two entities can activate grid charging.

This mode is ideal for dynamic pricing scenarios where you want full control over the triggering logic — for example, charging only during the cheapest hours of the day without pre-computing a schedule overnight.

*   **Enable**: Check "Configure predictive charging" and select **Automation Slot (external price sensor)**.
*   **No additional settings**: The integration does not evaluate prices itself. All logic lives in the external automation.

*   **How it works**:
    1.  An external automation (e.g. the **Dynamic Price Charging** blueprint below) evaluates the current price at regular intervals.
    2.  When the price is cheap, the automation writes a future timestamp to `Automation Charging End Time` and turns on `Automation Charging Active`.
    3.  The integration's controller detects the active slot and starts grid charging immediately.
    4.  When `Automation Charging End Time` is reached, the controller automatically turns off the switch and returns to normal PD control.
    5.  If the next slot is also cheap, the automation renews the end time before expiry — charging continues uninterrupted.

> [!NOTE]
> A daily notification is sent at **23:00** with an energy balance assessment for the next day, so you know in advance whether the blueprint is likely to activate charging overnight.

## Blueprints

Ready-made automations to extend the integration's functionality.

### Dynamic Price Charging

Activates battery charging automatically when the current electricity price falls below a configurable threshold. Works with any HA price sensor (PVPC, Nordpool, Energi Data Service, etc.). Supports hourly and 15-minute price slots, a daily average threshold, and manual triggering.

Requires the integration to be configured in **Mode C — Automation Slot** (step 6 of the configuration wizard).

[![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fffunes%2Fmarstek-venus-energy-manager%2Fmain%2Fblueprints%2Fautomation%2Fmarstek_venus_energy_manager%2Fmarstek_dynamic_price_charging.yaml)

### 7. Weekly Full Charge (Optional)
LFP batteries need to hit 100% periodically to balance individual cells.
*   **Enable**: Check "Configure weekly full charge".
*   **Day**: Select the day of the week (e.g., `Sunday`) to force a charge to 100%, overriding any other limits.

### 8. Charge Delay (Optional)
Solar-aware charge delay that applies **every day**, not just on the weekly full charge day.
*   **Enable**: Check "Configure charge delay".
*   **How it works**: The system captures the solar forecast every night at 23:00. On the following day, it uses a sinusoidal solar production model to estimate remaining solar energy in real time. Charging is held back while solar can still cover the required energy, and unlocked automatically once the energy balance tips. On the weekly full charge day the target SOC is 100%; on all other days it targets the configured `max_soc`.
*   **Settings** (shown after enabling):
    *   **Solar Forecast Sensor**: Required if not already configured in Predictive Charging. Provides the next-day solar production estimate (kWh).
    *   **Safety Margin**: Minutes before sunset by which charging must be complete (30–180 min, default 180 min). Higher values unlock grid charging earlier in the day. This ensures charging finishes with enough buffer before sunset even if solar production slightly underperforms.
*   **Fallback**: If no forecast is available or the forecast is very low, the charge unlocks immediately at midnight (safe default).
*   **Runtime toggle**: The `Charge Delay` switch on the Marstek Venus System device lets you enable/disable the feature without reconfiguring the integration.

### 9. Capacity Protection (Optional)
Conserves battery energy during high-SOC periods to avoid unnecessary discharge when house loads spike.
*   **Enable**: Check "Configure capacity protection" in the options flow.
*   **Settings**:
    *   **SOC Threshold**: Below this SOC (default 30%), protection is active. Above it, the battery operates normally.
    *   **Peak Limit**: Maximum house load (W) the battery will cover. Consumption above this threshold is left to the grid; the battery only offsets the excess.
*   **Runtime toggle**: The `Capacity Protection` switch lets you enable/disable the feature without reconfiguring. Number entities for SOC threshold and peak limit allow in-place tuning.

### 10. Advanced PD Controller (Expert Mode)
> [!WARNING] 
> **EXPERT SETTINGS ONLY:** Do NOT modify these values unless you fully understand PID control theory and how it interacts with battery inverter response times. Incorrect tuning can cause power oscillations or unstable behavior.

The integration uses a PD (Proportional-Derivative) controller to manage battery power output based on grid consumption.
*   **Kp (Proportional Gain)**: Controls how aggressively the battery responds to grid imbalance. Higher values = faster response but potential for overshoot.
*   **Kd (Derivative Gain)**: Provides damping to prevent oscillations. Higher values = smoother transitions but slower settling time.
*   **Deadband**: The "ignore" zone around the target grid power (Watts). The battery won't adjust if grid power is within this range of the target, preventing constant micro-adjustments.
*   **Max Power Change**: The maximum allowable change in battery power output per control cycle (Watts). Prevents sudden large power swings that could stress the inverter.
*   **Direction Hysteresis**: The power threshold (Watts) required to switch between charging and discharging. Prevents rapid flipping between modes when consumption is hovering around zero.
*   **Minimum Charge Power**: If the PD controller calculates a charge power below this threshold, it stays idle instead. Prevents inefficient low-power charging that causes micro-cycling and battery wear. Default: `0W` (disabled). Range: `0W` to `500W`.
*   **Minimum Discharge Power**: Same as above but for discharging. Default: `0W` (disabled). Range: `0W` to `500W`.
---

## Entities & Controls

### System-Wide Entities
These controls affect the entire system or aggregate data from all batteries.

  - **Controls**: Manual Mode, Predictive Charging, Charge Delay, Capacity Protection, Time Slot switches, Weekly Full Charge Day select — all without `EntityCategory` so they appear in the Controls section.
    *   **Manual Mode (Switch)**: Pauses the automatic PD controller and predictive logic. Sets all batteries to an idle state (0W). Use this when you want to manually control charge/discharge rates via the slider controls on individual batteries.
    *   **Predictive Charging (Switch)**: Manually stops or prevents the predictive grid charging logic from running, even if the schedule and forecast conditions are met. Use this to skip a scheduled night charge.
    *   **Charge Delay (Switch)**: Enables or disables the solar-aware charge delay at runtime. Only visible when charge delay is configured. Toggling this off bypasses the delay and allows charging immediately.
    *   **Capacity Protection (Switch)**: Enables or disables capacity protection (peak shaving) at runtime. Only visible when the feature is configured.
    *   **Time Slot switches**: Enable/disable individual no-discharge time slots on the fly.
    *   **Weekly Full Charge Day select entity**: Pick the balancing day directly from the UI.
  - **Sensors**: Aggregated sensors for the whole battery bank.
  - **Configuration**: Kp, Kd, deadband, max power change, direction hysteresis, min charge/discharge power — all hot-reloadable without integration restart. Also: `Capacity Protection SOC Threshold` and `Capacity Protection Peak Limit` number entities (only visible when the feature is enabled).
  - **Diagnostic**: Discharge Window sensor, Predictive Charging Active binary sensor, Charge Delay Status sensor, Capacity Protection Active binary sensor.
    *   **Charge Delay Status sensor**: Shows the current state of the charge delay logic (`Idle`, `Waiting for solar`, `Delayed (~HH:MM est.)`, `Charging allowed`, or `Disabled`). Attributes expose forecast data, solar window, energy calculations, estimated unlock time, and unlock reason.
    *   **Capacity Protection Active binary sensor**: Turns ON when protection is actively intervening (SOC below threshold). Attributes expose `avg_soc`, `soc_threshold`, `peak_limit_w`, `estimated_house_load_w`, `action`, `original_target_w`, and `adjusted_target_w`.
    *   **Excluded Devices Config sensor**: Read-only diagnostic showing the number of excluded devices, with per-device details (sensor entity, included_in_consumption, allow_solar_surplus) as attributes.
    *   **Discharge Window diagnostic sensor**: Real-time sensor showing whether the system is currently inside an allowed discharge time slot. Displays "Active (Slot N)", "Inactive", or "No slots". Attributes include all slot configuration details (schedule, days, enabled, apply_to_charge, target_grid_power).
    *   **Active Batteries diagnostic sensor**: Real-time sensor showing which batteries are currently active in load sharing. Displays "Discharging: Venus 1", "Charging: Venus 2", or "Idle". Attributes include per-battery SOC, lifetime discharged/charged energy, and active battery counts. Only created for multi-battery setups.

### Individual Battery Entities
For each configured battery (`Device`), you will see:

*   **Sensors**:
    *   `Battery SOC`: State of Charge (%)
    *   `Battery Power`: Real-time power (- Charging, + Discharging)
    *   `Voltage`, `Current`, `Internal Temperature`
    *   `Round-Trip Efficiency Total`: Calculated efficiency based on total charge/discharge energy.
*   **Diagnostic**:
    *   `Max Cell Voltage`, `Min Cell Voltage` (Health metrics)
    *   `Inverter State` (e.g., Standby, Charge, Discharge)
    *   `Fault Status`, `Alarm Status`
*   **Manual Controls** (Used mainly when **Manual Mode** is ON):
    *   **Set Forcible Charge Power**: Slider to set a fixed charge rate (Watts).
    *   **Set Forcible Discharge Power**: Slider to set a fixed discharge rate (Watts).
    *   **Reset Device**: Button to soft-reset the battery/inverter.
*   **Configuration Controls**:
    *   **Force Mode**: Select `Charge`, `Discharge`, or `None`.
    *   **Max Charge Power**: Slider to limit maximum charging speed (hardware limit).
    *   **Max Discharge Power**: Slider to limit maximum discharge speed (hardware limit).
*   **Switches**:
    *   `Backup Function`: Toggle backup output (if wired).

## Testbed Configuration

The development and testing of this integration were performed using the following hardware setup:

*   **Batteries**: 2x Marstek Venus E v2 units and 2x v3 units.
*   **Connectivity**: Elfin-EW11 Modbus to WiFi converter.
*   **Metering**: Shelly Pro 3EM Energy Meter (providing the grid consumption data).

## Acknowledgements

*   **Modbus Registers**: Special thanks to [ViperRNMC/marstek_venus_modbus](https://github.com/ViperRNMC/marstek_venus_modbus) for providing the essential Modbus register documentation that made this integration possible.

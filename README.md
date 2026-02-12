# Marstek Venus Energy Manager


The **Marstek Venus Energy Manager** is a comprehensive Home Assistant integration designed to monitor and control Marstek Venus E series batteries (v2 and v3 (untested)) via Modbus TCP. It provides advanced energy management features including predictive grid charging, customizable time slots for discharge control, and device load exclusion logic.

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

<a href="https://buymeacoffee.com/ffunes" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>


## Key Features

*   **Real-time Monitoring**: View battery SOC, power flow (charge/discharge), voltage, current, temperature, and cell-level health data.
*   **Multi-Battery Support**: Seamlessly manage up to 4 batteries as a single system with aggregated system-wide sensors.
*   **Smart Energy Management**:
    *   **Predictive Grid Charging**: Automatically charge from the grid during cheap off-peak hours based on solar forecasts to ensure sufficient energy for the next day.
    *   **No-Discharge Time Slots**: Prevent battery discharge during specific times (e.g., peak grid rates) while still allowing charging.
    *   **Weekly Full Charge**: Option to force a full charge once a week for cell balancing and health maintenance.
    *   **Load Exclusion**: "Hide" specific heavy loads (like EV chargers) from the battery to prevent rapid draining, effectively reserving battery power for household baseload.
*   **Hardware Control**:
    *   Set maximum charge and discharge power limits.
    *   Configure minimum and maximum SOC operational limits.
    *   Force charge or discharge modes manually.

## Requirements

*   **Hardware:** 
    *   Marstek Venus E v2/v3 Battery.
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

### 3. Battery Setup
*   **Number of Batteries**: Select how many Marstek Venus units you have (1-4).
*   **Battery Configuration** (Repeated for each battery):
    *   **Name**: Give your battery a unique name (e.g., "Venus Battery 1").
    *   **Host**: The IP address of the battery (or the Modbus-TCP bridge/stick connected to it).
    *   **Port**: The Modbus TCP port (default is `502`).
    *   **Version**: Select your battery model (`v1/v2` or `v3`).
    *   **Max Charge/Discharge Power**: Select the rated power of your model (e.g., `2500W`).
    *   **SOC Limits**:
        *   **Max SOC**: Stop charging at this percentage (default 100%).
        *   **Min SOC**: Stop discharging at this percentage (default 12%).
    *   **Charge Hysteresis**: (Optional) Prevent rapid cycling near the charge limit.

### 4. Time Slots (Optional)
You can define specific time periods where the battery is **forbidden from discharging**. This is useful for saving battery power for evening peaks or overnight usage.
*   **Enable**: Check "Configure time slots".
*   **Add Slot**:
    *   **Start/End Time**: Define the window (e.g., `14:00` to `18:00`).
    *   **Days**: Select applicable days of the week.
    *   **Apply to charge**: (Advanced) If checked, this slot also restricts charging.

### 5. Excluded Devices (Optional)
This feature allows you to "mask" high-power devices so the battery doesn't try to cover their load. For example, if you turn on a 7kW car charger, you might not want your 2.5kW battery to drain itself instantly.
*   **Enable**: Check "Configure excluded devices".
*   **Add Device**:
    *   **Power Sensor**: The entity measuring the power of the heavy load (e.g., `sensor.wallbox_power`).
    *   **Included in Consumption**: Check this if your *Main Household Sensor* (step 2) already sees this load. Uncheck if it's on a separate circuit not monitored by the main sensor.

### 6. Predictive Charging (Optional)
Automatically charge the battery from the grid during a specific window if tomorrow's solar forecast is low.
*   **Enable**: Check "Configure predictive charging".
*   **Settings**:
    *   **Time Window**: When effectively to charge from grid (usually night time/off-peak, e.g., `02:00` - `05:00`).
    *   **Solar Forecast Sensor**: A sensor providing tomorrow's energy production estimate in **kWh** (e.g., from Solcast or Forecast.Solar).
    *   **Max Contracted Power**: The limit of your grid connection (W). The system ensures charging + house load doesn't trip your main breaker.

> [!NOTE]
> **Notification**: The system will send a Home Assistant notification **one hour before** the configured start time. This notification details the calculated required charge and whether grid charging will be activated. This gives you sufficient time to use the **Override Predictive Charging** switch if you disagree with the decision.

### 7. Weekly Full Charge (Optional)
LFP batteries need to hit 100% periodically to balance individual cells.
*   **Enable**: Check "Configure weekly full charge".
*   **Day**: Select the day of the week (e.g., `Sunday`) to force a charge to 100%, overriding any other limits.

### 8. Advanced PD Controller (Expert Mode)
> [!WARNING] 
> **EXPERT SETTINGS ONLY:** Do NOT modify these values unless you fully understand PID control theory and how it interacts with battery inverter response times. Incorrect tuning can cause power oscillations or unstable behavior.

The integration uses a PD (Proportional-Derivative) controller to manage battery power output based on grid consumption.
*   **Kp (Proportional Gain)**: Controls how aggressively the battery responds to grid imbalance. Higher values = faster response but potential for overshoot.
*   **Kd (Derivative Gain)**: Provides damping to prevent oscillations. Higher values = smoother transitions but slower settling time.
*   **Deadband**: The "ignore" zone around zero grid export/import (Watts). The battery won't adjust if grid power is within this range, preventing constant micro-adjustments.
*   **Max Power Change**: The maximum allowable change in battery power output per control cycle (Watts). Prevents sudden large power swings that could stress the inverter.
*   **Direction Hysteresis**: The power threshold (Watts) required to switch between charging and discharging. Prevents rapid flipping between modes when consumption is hovering around zero.

---

## Entities & Controls

### System-Wide Entities
These controls affect the entire system or aggregate data from all batteries.

*   **Marstek Venus System SOC/Power/Energy**: Aggregated sensors for the whole battery bank.
*   **Manual Mode (Switch)**:
    *   **Action**: Pauses the automatic PD controller and predictive logic. Sets all batteries to an idle state (0W).
    *   **Use Case**: Enable this when you want to manually control charge/discharge rates using the slider controls on individual batteries.
*   **Override Predictive Charging (Switch)**:
    *   **Action**: Manually stops or prevents the predictive grid charging logic from running, even if the schedule and forecast conditions are met.
    *   **Use Case**: Skip a scheduled night charge if you know you won't need it.

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

*   **Batteries**: 2x Marstek Venus E v2 units.
*   **Connectivity**: Elfin-EW11 Modbus to WiFi converter.
*   **Metering**: Shelly Pro 3EM Energy Meter (providing the grid consumption data).

## Acknowledgements

*   **Modbus Registers**: Special thanks to [ViperRNMC/marstek_venus_modbus](https://github.com/ViperRNMC/marstek_venus_modbus) for providing the essential Modbus register documentation that made this integration possible.

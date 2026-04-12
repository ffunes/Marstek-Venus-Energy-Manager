# Main sensor

The first step configures the global data sources for the integration.

## Grid consumption sensor

A Home Assistant sensor that measures power exchange with the grid (in **W** or **kW**).

!!! tip "Compatible sensors"
    Any sensor that exposes grid power works: Shelly EM, Shelly EM3, Neurio, smart meter integrations (e.g. `sensor.grid_power`).

!!! warning "Update frequency"
    The sensor should update as fast as possible. The controller runs every **2.5 seconds** and makes decisions based on the most recent reading available — the older the reading, the less accurate the response.

    Home consumption can vary by several kilowatts in fractions of a second (appliance start-ups, oven, washing machine…). A sensor that reports every 10 seconds or more introduces a lag that causes the controller to react to a situation that no longer exists, leading to overshoot or unnecessary corrections.

    **Recommended: 1–2 second update interval.** Devices like Shelly EM/EM3 support this natively.

### Automatic kW detection

If the sensor's `unit_of_measurement` attribute is `kW`, the integration multiplies the value by 1000 automatically.

### Inverted sign

Enable **"Inverted meter sign"** if your sensor uses the opposite convention:

| Convention | Import | Export |
|---|---|---|
| Standard (default) | Positive value | Negative value |
| Inverted | Negative value | Positive value |

Leave it disabled if you are unsure.

---

## Solar forecast sensor *(optional)*

Sensor providing tomorrow's estimated solar production in **kWh** or **Wh**.

Configuring it here makes it available to:

- **Predictive charging** (Time Slot and Dynamic Pricing modes)
- **Solar charge delay**

You can also leave it blank and configure it later in those specific sections.

<<<<<<< Updated upstream
![Configuración del sensor principal](../assets/screenshots/configuration/main-sensor.png){ width="600"  style="display: block; margin: 0 auto;"}
=======
---

## Household consumption sensor *(optional)*

A power sensor (W or kW) that measures total household electricity consumption.

When configured, the integration integrates the sensor reading over time — only during the **solar+battery window** (outside the charging time slot) — to produce a daily kWh figure. This replaces the default estimation method, which derives consumption from battery discharge + grid import at min SOC.

**When to configure it:**

- You have a clamp meter, Shelly EM, or similar device measuring total house load.
- You want predictive charging and charge delay to use real consumption data.
- Your solar production varies significantly week to week (high-solar weeks cause the default estimation to underestimate demand).

**How it works:**

| Mode | Consumption source |
|------|-------------------|
| Sensor configured | Integration of the power sensor (W→kWh) during the solar+battery window |
| No sensor | Battery discharge + grid import at min SOC (existing behaviour) |

The integration accumulates energy during the solar+battery window only (i.e. outside the configured charging time slot). If no time slot is configured, it accumulates all day. The counter resets at midnight and survives HA restarts.

The daily consumption figure feeds the same history that predictive charging and charge delay read — no additional configuration is needed in those sections.

!!! tip "Supported units"
    Both **W** and **kW** sensors are accepted. The integration reads the `unit_of_measurement` attribute and converts automatically.

![Main sensor configuration](../assets/screenshots/configuration/main-sensor.png){ width="600"  style="display: block; margin: 0 auto;"}
>>>>>>> Stashed changes

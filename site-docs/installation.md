# Installation

## Requirements

### Hardware

| Component | Description |
|---|---|
| Battery | Marstek Venus E v2/v3, Venus A or Venus D |
| Modbus converter | RS485 → Modbus TCP device (e.g. Elfin-EW11) — **Venus E v2 only**. Venus E v3, Venus A and Venus D connect via Ethernet and support Modbus TCP natively. |
| Grid sensor | HA sensor measuring total grid consumption (e.g. Shelly EM3, Neurio, smart meter integration) |

### Software

- Home Assistant **2024.1.0** or later
- (Optional) Solar forecast sensor for predictive charging (Solcast, Forecast.Solar, etc.)

### Network

The battery must be reachable from Home Assistant by IP on the same network segment or via routing.

---

## Installation via HACS (recommended)

1. Click the button to add the repository to HACS:

    [![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ffunes&repository=Marstek-Venus-Energy-Manager&category=integration)

2. Search for **"Marstek Venus Energy Manager"** and install.
3. Restart Home Assistant.

![HACS search](assets/screenshots/installation/hacs-search.png){ width="700"  style="display: block; margin: 0 auto;"}

---

## Manual installation

1. Download the zip from the latest release at [GitHub Releases](https://github.com/ffunes/Marstek-Venus-Energy-Manager/releases).
2. Extract the `marstek_venus_energy_manager` folder.
3. Copy it to the `custom_components/` directory of your Home Assistant instance.
4. Restart Home Assistant.

---

## Adding the integration

After installing and restarting:

1. Go to **Settings** → **Devices & Services**.
2. Click **+ ADD INTEGRATION**.
3. Search for **Marstek Venus Energy Manager**.
4. Follow the [configuration wizard](configuration/index.md).

![Add integration in HA](assets/screenshots/installation/add-integration.png){ width="600"  style="display: block; margin: 0 auto;"}

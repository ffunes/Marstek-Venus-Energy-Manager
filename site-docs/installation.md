# Instalación

## Requisitos

### Hardware

| Componente | Descripción |
|---|---|
| Batería | Marstek Venus E v2/v3, Venus A o Venus D |
| Conversor Modbus | Dispositivo RS485 → Modbus TCP (p. ej. Elfin-EW11) |
| Sensor de red | Sensor HA que mide el consumo total de la red (p. ej. Shelly EM3, Neurio, contador inteligente) |

### Software

- Home Assistant **2024.1.0** o superior
- (Opcional) Sensor de previsión solar para la carga predictiva (Solcast, Forecast.Solar, etc.)

### Red

La batería debe ser accesible desde Home Assistant por IP en el mismo segmento de red o mediante enrutamiento.

---

## Instalación con HACS (recomendado)

1. Haz clic en el botón para añadir el repositorio a HACS:

    [![Añadir a HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ffunes&repository=Marstek-Venus-Energy-Manager&category=integration)

2. Busca **"Marstek Venus Energy Manager"** e instala.
3. Reinicia Home Assistant.

![Búsqueda en HACS](assets/screenshots/installation/hacs-search.png){ width="700"  style="display: block; margin: 0 auto;"}

---

## Instalación manual

1. Descarga el zip de la última release desde [GitHub Releases](https://github.com/ffunes/Marstek-Venus-Energy-Manager/releases).
2. Extrae la carpeta `marstek_venus_energy_manager`.
3. Cópiala en el directorio `custom_components/` de Home Assistant.
4. Reinicia Home Assistant.

---

## Añadir la integración

Después de instalar y reiniciar:

1. Ve a **Ajustes** → **Dispositivos y servicios**.
2. Pulsa **+ AÑADIR INTEGRACIÓN**.
3. Busca **Marstek Venus Energy Manager**.
4. Sigue el [asistente de configuración](configuration/index.md).

![Añadir integración en HA](assets/screenshots/installation/add-integration.png){ width="600"  style="display: block; margin: 0 auto;"}

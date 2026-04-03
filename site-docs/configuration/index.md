# Configuración

La integración se configura íntegramente desde la interfaz de Home Assistant mediante un asistente de varios pasos.

## Pasos del asistente

```mermaid
flowchart TD
    A[1. Sensor principal] --> B[2. Número de baterías]
    B --> C[3. Config. por batería]
    C --> D{¿Franjas horarias?}
    D -- Sí --> E[4. Franjas horarias]
    D -- No --> F
    E --> F{¿Dispositivos excluidos?}
    F -- Sí --> G[5. Dispositivos excluidos]
    F -- No --> H
    G --> H{¿Carga predictiva?}
    H -- Sí --> I[6. Modo de carga predictiva]
    H -- No --> J[Fin]
    I --> J
```

| Paso | Descripción | Obligatorio |
|------|-------------|:-----------:|
| [Sensor principal](main-sensor.md) | Sensor de consumo de red y sensor solar | ✅ |
| Baterías | Número de unidades y configuración por batería | ✅ |
| [Baterías](batteries.md) | IP, puerto, versión, límites de potencia y SOC | ✅ |
| [Franjas horarias](time-slots.md) | Ventanas de descarga con parámetros por franja | ❌ |
| [Dispositivos excluidos](excluded-devices.md) | Cargas pesadas a ignorar | ❌ |
| [Carga predictiva](predictive-charging/index.md) | Carga desde la red cuando la previsión solar es insuficiente | ❌ |
| [Opciones avanzadas](advanced.md) | Carga semanal, retraso solar, peak shaving | ❌ |

## Modificar la configuración

Una vez instalada, puedes modificar cualquier parámetro en:
**Ajustes → Dispositivos y servicios → Marstek Venus Energy Manager → Configurar**

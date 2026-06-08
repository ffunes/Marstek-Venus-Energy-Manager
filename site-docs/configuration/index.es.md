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
    H -- No --> J
    I --> J{¿Carga semanal completa?}
    J -- Sí --> K[7. Día de carga semanal completa]
    J -- No --> L
    K --> L{¿Retraso de carga solar?}
    L -- Sí --> M[8. Config. retraso de carga solar]
    L -- No --> N
    M --> N{¿Protección de capacidad?}
    N -- Sí --> O[9. Config. protección de capacidad]
    N -- No --> P
    O --> P{¿Balance neto horario?}
    P -- Sí --> Q[10. Config. balance neto horario]
    P -- No --> R
    Q --> R{¿Controlador PD avanzado?}
    R -- Sí --> S[11. Config. controlador PD avanzado]
    R -- No --> T[Fin]
    S --> T
```

| Paso | Descripción | Obligatorio |
|------|-------------|:-----------:|
| [Sensor principal](main-sensor.md) | Sensor de consumo de red y sensor solar (el consumo del hogar se deriva) | ✅ |
| Baterías | Número de unidades | ✅ |
| [Baterías](batteries.md) | Config. por batería: nombre, IP, puerto, versión, límites de potencia y SOC | ✅ |
| [Franjas horarias](time-slots.md) | Ventanas de descarga/carga con parámetros por franja | ❌ |
| [Dispositivos excluidos](excluded-devices.md) | Cargas pesadas a ignorar | ❌ |
| [Carga predictiva](predictive-charging/index.md) | Carga desde la red cuando la previsión solar es insuficiente | ❌ |
| [Carga semanal completa](advanced.md) | Carga las baterías al 100% una vez a la semana para equilibrar las celdas | ❌ |
| [Retraso de carga solar](advanced.md) | Evita cargar las baterías por la mañana si la producción solar prevista será suficiente | ❌ |
| [Protección de capacidad](advanced.md) | Reserva una parte de la capacidad de batería para picos de demanda (peak shaving) | ❌ |
| [Balance neto horario](advanced.md) | Establece el balance neto de importación/exportación horario a un objetivo específico (por defecto 0 Wh) | ❌ |
| [Controlador PD (avanzado)](advanced.md) | Ajuste fino del controlador PD para mantener el flujo de red en el objetivo configurado | ❌ |

## Modificar la configuración

Una vez instalada, puedes modificar cualquier parámetro en:
**Ajustes → Dispositivos y servicios → Marstek Venus Energy Manager → Configurar**

![Reconfigure Marstek Venus Energy Manager](../assets/screenshots/configuration/reconfigure-marstek-venus-energy-manager.png){ width="650" style="display: block; margin: 0 auto;"}

# Arquitectura

## Componentes principales

```mermaid
flowchart TD
    GS[Sensor de red HA] --> CC[ChargeDischargeController\n__init__.py]
    CC --> PD[Algoritmo PD]
    PD --> DIST[Distribución de potencia\nmulti-batería]
    DIST --> MW[Escritura Modbus]
    MW --> BAT1[Batería 1]
    MW --> BAT2[Batería 2..4]

    COORD[MarstekVenusDataUpdateCoordinator\ncoordinator.py] --> MR[Lectura Modbus]
    MR --> BAT1
    MR --> BAT2
    COORD --> EU[Actualización de entidades HA]

    MC[MarstekModbusClient\nmodbus_client.py] --> MW
    MC --> MR
```

## Módulos

| Archivo | Clase principal | Responsabilidad |
|---|---|---|
| `__init__.py` | `ChargeDischargeController` | Bucle de control principal (cada 2,5 s), algoritmo PD, distribución multi-batería |
| `coordinator.py` | `MarstekVenusDataUpdateCoordinator` | Polling periódico de datos Modbus, actualización de entidades |
| `modbus_client.py` | `MarstekModbusClient` | Comunicación TCP asíncrona con pymodbus, reintentos con backoff |
| `config_flow.py` | — | Asistente de configuración multi-paso en HA UI |
| `const.py` | — | Definiciones de todos los registros Modbus y entidades |
| `aggregate_sensors.py` | — | Sensores agregados del sistema (suma de todas las baterías) |
| `calculated_sensors.py` | — | Sensores derivados calculados (ciclos, estimaciones) |

## Flujo de datos

```
Sensor de red → Controlador (PD) → Distribución de potencia → Escritura Modbus → Baterías
                      ↑
Coordinador → Lectura Modbus → Actualización de entidades
```

## Intervalos de polling

| Intervalo | Período | Registros |
|---|---|---|
| `high` | 2 s | Potencia, SOC |
| `medium` | 5 s | Tensión, corriente, temperatura |
| `low` | 30 s | Energía acumulada, alarmas |
| `very_low` | 300 s | Info de dispositivo, firmware |

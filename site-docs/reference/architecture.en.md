# Architecture

## Main components

```mermaid
flowchart TD
    GS[HA Grid Sensor] --> CC[ChargeDischargeController\n__init__.py]
    CC --> PD[PD Algorithm]
    PD --> DIST[Power distribution\nmulti-battery]
    DIST --> MW[Modbus write]
    MW --> BAT1[Battery 1]
    MW --> BAT2[Battery 2..4]

    COORD[MarstekVenusDataUpdateCoordinator\ncoordinator.py] --> MR[Modbus read]
    MR --> BAT1
    MR --> BAT2
    COORD --> EU[HA entity updates]

    MC[MarstekModbusClient\nmodbus_client.py] --> MW
    MC --> MR
```

## Modules

| File | Main class | Responsibility |
|---|---|---|
| `__init__.py` | `ChargeDischargeController` | Main control loop (every 2.5 s), PD algorithm, multi-battery distribution |
| `coordinator.py` | `MarstekVenusDataUpdateCoordinator` | Periodic Modbus data polling, entity updates |
| `modbus_client.py` | `MarstekModbusClient` | Async TCP communication via pymodbus, retries with backoff |
| `config_flow.py` | — | Multi-step configuration wizard in HA UI |
| `const.py` | — | All Modbus register and entity definitions |
| `aggregate_sensors.py` | — | System aggregate sensors (sum across all batteries) |
| `calculated_sensors.py` | — | Derived calculated sensors (cycle count, estimates) |

## Data flow

```
Grid sensor → Controller (PD) → Power distribution → Modbus write → Batteries
                    ↑
Coordinator → Modbus read → Entity updates
```

## Polling intervals

| Interval | Period | Registers |
|---|---|---|
| `high` | 2 s | Power, SOC |
| `medium` | 5 s | Voltage, current, temperature |
| `low` | 30 s | Accumulated energy, alarms |
| `very_low` | 300 s | Device info, firmware |

# Retraso de carga solar

Retrasa la carga matutina desde la red mientras la producción solar prevista sea suficiente para cubrir la energía necesaria. Evita comprar energía de la red que luego sería desplazada por la solar.

## Aplicación

- Carga matutina normal (cuando la batería se ha descargado durante la noche).
- Carga semanal al 100 % (espera a que el sol complete la carga antes de recurrir a la red).

## Modelo solar

La integración usa un **modelo sinusoidal** basado en la previsión nocturna almacenada para estimar la producción solar hora a hora a lo largo del día. Compara la producción acumulada esperada desde la hora actual hasta el anochecer con la energía que falta por cargar.

```
Si producción_solar_restante >= energía_a_cargar:
    Esperar (el sol lo cargará)
Si no:
    Iniciar carga desde la red
```

## Previsión nocturna almacenada

Cada noche, la integración guarda la previsión solar del día siguiente. Esta previsión almacenada se usa durante todo el día siguiente para el modelo de retraso, garantizando una estimación coherente incluso si el sensor de previsión cambia durante el día.

## Requisitos

- Sensor de previsión solar configurado en el [paso inicial](../configuration/main-sensor.md).

![Atributos del retraso de carga solar](../assets/screenshots/features/solar-charge-delay-attributes.png){ width="650"  style="display: block; margin: 0 auto;"}

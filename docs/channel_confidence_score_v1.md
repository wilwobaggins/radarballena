````md
# Channel Confidence Score v1

## 1. Objetivo

Crear un score inicial para clasificar los canales actuales de Smart Money Whales en RadarBallena.

Este score no reemplaza el análisis manual ni el `whale-finder`. Sirve como una primera capa para decidir qué canales mostrar en beta, cuáles marcar como experimentales y cuáles revisar antes de destacarlos.

---

## 2. Fórmula v1

El score se calcula sobre 100 puntos:

```txt
Channel Confidence Score =
35% win_rate_score
+ 20% alert_count_score
+ 20% avg_volume_score
+ 15% recent_activity_score
+ 10% category_consistency_score
````

### Componentes

#### 1. Win rate score — 35%

Usa el win rate de alertas resueltas.

```txt
win_rate_score = win_rate_pct
```

Ejemplo:

```txt
63.37% win rate = 63.37 puntos
```

#### 2. Alert count score — 20%

Mide cantidad de alertas emitidas.

```txt
alert_count_score = min(total_alerts / 1000 * 100, 100)
```

Canales con 1000+ alertas reciben 100 puntos en este componente.

#### 3. Avg volume score — 20%

Mide tamaño promedio de las alertas.

```txt
avg_volume_score = min(avg_volume_usd / 5000 * 100, 100)
```

Canales con volumen promedio de $5,000+ reciben 100 puntos en este componente.

#### 4. Recent activity score — 15%

Mide si el canal sigue activo.

```txt
Última alerta en 0-2 días = 100
Última alerta en 3-7 días = 75
Última alerta en 8-14 días = 50
Más de 14 días = 25
Sin actividad = 0
```

#### 5. Category consistency score — 10%

Evaluación cualitativa de si el canal realmente corresponde a su categoría/nombre.

```txt
Muy consistente = 90-100
Consistente = 75-89
Mixto pero usable = 60-74
Confuso = 30-59
Inconsistente = 0-29
```

---

## 3. Reglas de etiquetado

Labels disponibles:

```txt
Verified Channel
High Confidence
Active Signal
Experimental
Noise Risk
Insufficient Data
```

Criterio base:

```txt
75+ = Verified Channel
65-74 = High Confidence
55-64 = Active Signal
40-54 = Experimental
25-39 = Noise Risk
<25 = Insufficient Data
```

Reglas de override:

```txt
Si resolved_alerts < 5 → Insufficient Data
Si resolved_alerts < 20 y win_rate < 50% → Noise Risk / Insufficient Data
Si win_rate < 50% con muestra suficiente → Experimental aunque el score sea mayor
Si whale-finder marca degraded → no asignar Verified Channel
```

---

## 4. Datos usados

| Canal                      | Total alerts | Resueltas | Wins | Losses | Avg volume USD | Last alert |
| -------------------------- | -----------: | --------: | ---: | -----: | -------------: | ---------- |
| Geopolitical Macro Whale   |         1228 |       112 |   51 |     61 |       1,142.88 | 2026-05-26 |
| NBA Volume Trader Theta    |         1086 |       606 |  328 |    278 |       1,823.35 | 2026-05-26 |
| Global Sports Arb Lambda   |          314 |       202 |  128 |     74 |       5,039.95 | 2026-05-26 |
| Everything Trader Zeta     |          150 |        58 |   34 |     23 |       6,064.07 | 2026-05-20 |
| Macro Economics Whale      |          126 |         1 |    0 |      1 |         875.75 | 2026-05-26 |
| Soccer Esports Titan Alpha |          108 |        10 |    2 |      8 |       1,455.84 | 2026-05-26 |

---

## 5. Score aplicado a canales actuales

| Canal                      | Win rate | Score v1 | Label             | Recomendación beta                           |
| -------------------------- | -------: | -------: | ----------------- | -------------------------------------------- |
| Global Sports Arb Lambda   |   63.37% |       72 | High Confidence   | Mostrar en beta                              |
| NBA Volume Trader Theta    |   54.13% |       71 | High Confidence   | Mostrar en beta                              |
| Everything Trader Zeta     |   59.65% |       62 | Active Signal     | Mostrar en beta                              |
| Geopolitical Macro Whale   |   45.54% |       63 | Experimental      | Mostrar con etiqueta experimental            |
| Soccer Esports Titan Alpha |   20.00% |       32 | Noise Risk        | No destacar / revisar                        |
| Macro Economics Whale      |    0.00% |       27 | Insufficient Data | No evaluar todavía por falta de resoluciones |

---

## 6. Lectura por canal

## Global Sports Arb Lambda

Score v1:

```txt
72 / 100
```

Label:

```txt
High Confidence
```

Motivo:

* Mejor win rate actual.
* 202 alertas resueltas.
* Volumen promedio alto.
* Actividad reciente.
* Aunque el whale-finder marca degradación por patrones de hedging, el histórico de resultados sigue siendo fuerte.

Recomendación:

```txt
Mostrar en beta.
Agregar monitoreo por riesgo de hedging.
```

---

## NBA Volume Trader Theta

Score v1:

```txt
71 / 100
```

Label:

```txt
High Confidence
```

Motivo:

* Mayor muestra resuelta: 606 alertas.
* Win rate positivo.
* Mucha actividad histórica.
* Canal fácil de entender para usuario final.

Recomendación:

```txt
Mostrar en beta.
No marcar como Verified todavía por flags del whale-finder.
```

---

## Everything Trader Zeta

Score v1:

```txt
62 / 100
```

Label:

```txt
Active Signal
```

Motivo:

* Buen win rate.
* Volumen promedio alto.
* Muestra menor que NBA y Sports Arb.
* Última alerta menos reciente, pero todavía dentro de rango activo.

Recomendación:

```txt
Mostrar en beta.
Tratar como canal mixto, no como señal especializada.
```

---

## Geopolitical Macro Whale

Score v1:

```txt
63 / 100
```

Label:

```txt
Experimental
```

Motivo:

* Muchísimas alertas.
* Actividad reciente.
* Win rate menor a 50%.
* Muchos mercados geopolíticos tardan en resolverse, por lo que el score puede mejorar o empeorar con más cierres.

Recomendación:

```txt
Mostrar solo como experimental.
No presentarlo como canal confiable todavía.
```

---

## Soccer Esports Titan Alpha

Score v1:

```txt
32 / 100
```

Label:

```txt
Noise Risk
```

Motivo:

* Win rate bajo.
* Solo 10 alertas resueltas.
* Posible inconsistencia entre nombre del canal y comportamiento real.
* Whale-finder lo marca como watch, pero no como canal confiable.

Recomendación:

```txt
No destacarlo en beta.
Revisar nombre, perfil y posible reemplazo.
```

---

## Macro Economics Whale

Score v1:

```txt
27 / 100
```

Label:

```txt
Insufficient Data
```

Motivo:

* Solo 1 alerta resuelta.
* No hay muestra estadística suficiente.
* El win rate no debe usarse aún como conclusión.
* Actividad reciente existe, pero no hay resolución suficiente.

Recomendación:

```txt
No clasificar como bueno o malo todavía.
Mostrar solo si se etiqueta claramente como Insufficient Data.
```

---

## 7. Canales recomendados para beta

## Mostrar en beta principal

| Canal                    | Label           |
| ------------------------ | --------------- |
| Global Sports Arb Lambda | High Confidence |
| NBA Volume Trader Theta  | High Confidence |
| Everything Trader Zeta   | Active Signal   |

## Mostrar como experimental

| Canal                    | Label        |
| ------------------------ | ------------ |
| Geopolitical Macro Whale | Experimental |

## No destacar todavía

| Canal                      | Label             |
| -------------------------- | ----------------- |
| Soccer Esports Titan Alpha | Noise Risk        |
| Macro Economics Whale      | Insufficient Data |

---

## 8. Notas importantes

El score v1 es inicial y debe actualizarse cuando haya más alertas resueltas.

No debe usarse como única autoridad para reemplazar wallets. El `whale-finder` sigue siendo la capa de auditoría de wallets.

El score mide confianza de canal para UX/producto, no necesariamente calidad pura de la wallet.

---

## 9. Estado de la tarjeta

Checklist:

```txt
Definir fórmula v1: completado.
Aplicarla a canales actuales: completado.
Etiquetar canales: completado.
Documentar criterios: completado.
Recomendar qué mostrar al usuario beta: completado.
```

Definition of Done:

```txt
Score aplicado a canales actuales: completado.
```

```
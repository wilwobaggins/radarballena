````md
# Auditoría Smart Money Whales actual

## 1. Objetivo

Este documento audita los 6 canales/wallets actuales de Smart Money Whales en RadarBallena.

La auditoría cruza tres fuentes:

1. Configuración actual del `whale-worker`.
2. Métricas históricas de alertas desde la base de datos.
3. Evaluación del `whale-finder` sobre salud de wallets y posibles reemplazos.

El objetivo es definir qué canales pueden mostrarse en beta, cuáles deben marcarse como experimentales y cuáles requieren revisión.

---

## 2. Canales actuales

| Whale ID | Canal / Nombre visible | Wallet | Min USDC | Tipo actual |
|---|---|---:|---:|---|
| `nba_volume` | NBA Volume Trader Theta | `0x32ed517a571c01b6e9adecf61ba81ca48ff2f960` | 200 | Sports / NBA |
| `sports_arb` | Global Sports Arb Lambda | `0x479e330b07822ee28e20bac5e504f1b7c6b591c3` | 500 | Sports global |
| `global_trader` | Everything Trader Zeta | `0x9d84ce0306f8551e02efef1680475fc0f1dc1344` | 300 | Mixto / global |
| `macro_economics` | Macro Economics Whale | `0xc8ab97a9089a9ff7e6ef0688e6e591a066946418` | 150 | Macro |
| `geo_macro` | Geopolitical Macro Whale | `0xbacd00c9080a82ded56f504ee8810af732b0ab35` | 150 | Geopolítico |
| `sports_esports_titan` | Soccer Esports Titan Alpha | `0x2663daca3cecf3767ca1c3b126002a8578a8ed1f` | 175 | Sports / esports |

La configuración actual del worker confirma estos 6 canales activos y sus wallets monitoreadas. :contentReference[oaicite:0]{index=0}

---

## 3. Métricas históricas por canal

| Canal | Total alerts | Resueltas | Wins | Losses | Win rate | Loss rate | Lectura inicial |
|---|---:|---:|---:|---:|---:|---:|---|
| Geopolitical Macro Whale | 1224 | 112 | 51 | 61 | 45.54% | 54.46% | Mucha actividad, pero bajo cierre relativo y win rate débil. |
| NBA Volume Trader Theta | 1086 | 606 | 328 | 278 | 54.13% | 45.87% | Buen volumen histórico, rendimiento moderado. |
| Global Sports Arb Lambda | 314 | 202 | 128 | 74 | 63.37% | 36.63% | Mejor win rate actual; candidato fuerte para beta. |
| Everything Trader Zeta | 150 | 58 | 34 | 23 | 59.65% | 40.35% | Buen rendimiento relativo; muestra menor. |
| Macro Economics Whale | 126 | 1 | 0 | 1 | 0.00% | 100.00% | Muestra resuelta insuficiente; no se puede juzgar por win rate. |
| Soccer Esports Titan Alpha | 108 | 10 | 2 | 8 | 20.00% | 80.00% | Bajo rendimiento en muestra resuelta; requiere revisión. |

---

## 4. Evaluación del whale-finder

El `whale-finder` evaluó las wallets actuales y marcó 5 como `degraded` y 1 como `watch`.

| Canal | Health status | Score whale-finder | Flags principales | Acción sugerida por whale-finder |
|---|---:|---:|---|---|
| NBA Volume Trader Theta | degraded | 33 | opposing outcomes, heavy opposing outcomes | keep watch, no replacement |
| Global Sports Arb Lambda | degraded | 39 | opposing outcomes, heavy opposing outcomes | keep watch, no replacement |
| Everything Trader Zeta | degraded | 40 | opposing outcomes, heavy opposing outcomes | keep watch, no replacement |
| Macro Economics Whale | degraded | 32 | opposing outcomes, heavy opposing outcomes | keep watch, no replacement |
| Geopolitical Macro Whale | degraded | 32 | opposing outcomes, heavy opposing outcomes | keep watch, no replacement |
| Soccer Esports Titan Alpha | watch | 64 | mostly low price trades, extreme price volume | keep watch, no replacement |

El diagnóstico del whale-finder no recomienda reemplazo automático para ninguna wallet actual. El patrón más repetido es exceso de operaciones en outcomes opuestos, lo que puede indicar hedge, market making o arbitraje, no señal direccional limpia. :contentReference[oaicite:1]{index=1}

---

## 5. Clasificación recomendada

## 5.1 Canales confiables para beta

### Global Sports Arb Lambda

Motivo:

- Mejor win rate actual: 63.37%.
- 202 alertas resueltas.
- Buen volumen de alertas.
- Aunque el whale-finder lo marca `degraded`, el histórico de resultados todavía es fuerte.

Recomendación:

```txt
Mostrar en beta.
Etiqueta sugerida: Confiable / Sports.
Mantener monitoreo por flags de hedging.
````

### NBA Volume Trader Theta

Motivo:

* Mayor volumen útil después de Geopolitical.
* 606 alertas resueltas.
* Win rate positivo: 54.13%.
* Canal claro de lectura deportiva/NBA.

Recomendación:

```txt
Mostrar en beta.
Etiqueta sugerida: Confiable moderado / NBA.
Monitorear por posible degradación detectada por whale-finder.
```

### Everything Trader Zeta

Motivo:

* Win rate positivo: 59.65%.
* 58 alertas resueltas.
* Perfil mixto útil para diversificación.

Recomendación:

```txt
Mostrar en beta.
Etiqueta sugerida: Confiable / Mixto.
No sobredimensionar por muestra menor.
```

---

## 5.2 Canales experimentales

### Geopolitical Macro Whale

Motivo:

* Muchísimas alertas: 1224.
* Solo 112 resueltas.
* Win rate bajo: 45.54%.
* Los mercados geopolíticos suelen tardar más en resolverse, por lo que el win rate puede estar incompleto.
* Whale-finder lo marca `degraded`.

Recomendación:

```txt
Mostrar en beta solo como experimental.
Etiqueta sugerida: Experimental / Geopolítica.
No presentarlo como canal confiable todavía.
```

### Macro Economics Whale

Motivo:

* 126 alertas totales.
* Solo 1 alerta resuelta.
* No hay muestra suficiente para evaluar win rate.
* Whale-finder lo marca `degraded`.

Recomendación:

```txt
Mostrar como experimental o mantener oculto hasta tener más resolución.
Etiqueta sugerida: Experimental / Macro.
No usar win rate como métrica principal todavía.
```

---

## 5.3 Canal débil / revisar

### Soccer Esports Titan Alpha

Motivo:

* 108 alertas totales.
* 10 resueltas.
* Win rate bajo: 20%.
* Whale-finder lo marca `watch`, no `degraded`, pero su rendimiento histórico visible es débil.
* La evaluación detecta patrón de low price trades y extreme price volume.

Recomendación:

```txt
No destacarlo en beta.
Mantenerlo en revisión.
Buscar reemplazo o renombrar si el perfil real no corresponde a sports/esports.
```

---

## 6. Consistencia de nombres

Hay una posible inconsistencia importante:

```txt
sports_esports_titan → Soccer Esports Titan Alpha
```

Pero el whale-finder lo clasifica principalmente como `politics`, no como sports/esports.

Esto sugiere que el nombre visible puede no representar bien el comportamiento real de la wallet.

Recomendación:

```txt
Revisar nombre de Soccer Esports Titan Alpha.
No usarlo como canal sports/esports hasta validar su comportamiento.
```

También hay inconsistencias menores:

```txt
Macro Economics Whale
```

El whale-finder lo clasifica como sports en el resumen automático, pero sus sample trades muestran temas macro/geopolíticos como petróleo, Irán y Strait of Hormuz. Esto parece un problema de clasificación del auditor, no necesariamente del canal.

---

## 7. Recomendación para beta

## Mostrar en beta

| Canal                    | Motivo                                         |
| ------------------------ | ---------------------------------------------- |
| Global Sports Arb Lambda | Mejor win rate y buena muestra resuelta.       |
| NBA Volume Trader Theta  | Mayor muestra resuelta y rendimiento positivo. |
| Everything Trader Zeta   | Buen win rate y útil como canal mixto.         |

## Mostrar como experimental

| Canal                    | Motivo                                                              |
| ------------------------ | ------------------------------------------------------------------- |
| Geopolitical Macro Whale | Mucha actividad, pero win rate bajo y pocas resoluciones relativas. |
| Macro Economics Whale    | Sin muestra suficiente de resoluciones.                             |

## No destacar / revisar

| Canal                      | Motivo                                            |
| -------------------------- | ------------------------------------------------- |
| Soccer Esports Titan Alpha | Bajo win rate y posible inconsistencia de perfil. |

---

## 8. Riesgos detectados

### 1. Win rate incompleto

Muchos mercados siguen sin resolverse. Esto afecta especialmente a canales macro y geopolíticos.

### 2. Señal contaminada por hedging

El whale-finder detectó `opposing_outcomes_detected` y `heavy_opposing_outcomes` en varias wallets. Esto puede significar que algunas wallets no son apuestas direccionales limpias.

### 3. Canal ≠ wallet limpia

Algunos canales podrían representar una estrategia, cluster o comportamiento mixto, no necesariamente una sola señal direccional confiable.

### 4. Naming puede confundir

Al menos `Soccer Esports Titan Alpha` parece no coincidir bien con el comportamiento observado.

---

## 9. Decisión operativa

La decisión recomendada para MVP/beta es:

```txt
No eliminar wallets todavía.
No reemplazar automáticamente.
Mostrar solo las mejores como beta principal.
Marcar las dudosas como experimentales.
Seguir acumulando resolución real.
Usar whale-finder como auditor, no como autoridad automática.
```

---

## 10. Estado de la tarjeta

Checklist:

```txt
Listar los 6 canales actuales: completado.
Documentar alerts por canal: completado.
Documentar win rate por canal: completado.
Documentar loss rate: completado.
Revisar si canal = wallet, cluster o estrategia: completado parcialmente.
Identificar canales confiables: completado.
Identificar canales experimentales: completado.
Revisar consistencia de nombres: completado.
Revisar problemas de credibilidad: completado.
Definir cuáles canales deben mostrarse en beta: completado.
```

Definition of Done:

```txt
Tabla con canales, métricas y recomendación: completado.
```

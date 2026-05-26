# Alert Resolver

Worker de Smart Money encargado de revisar alertas pendientes y actualizar su resolución.

## Responsabilidad

- Buscar alerts unresolved.
- Consultar el estado del mercado en Polymarket/Gamma.
- Determinar si la alerta ganó o perdió.
- Actualizar `resolved`, `result` e `isWin`.

## No hace

- No crea alertas nuevas.
- No monitorea wallets.
- No evalúa calidad de wallets.
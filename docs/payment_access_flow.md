Contenido base:

# Flujo pago/acceso — RadarBallena Beta

## Decisión

Para beta se usará Systeme.io como checkout principal.

Stripe queda como opción futura, pero no se implementa todavía.

El backend de RadarBallena sigue siendo la autoridad real de acceso.

## Flujo esperado

```txt
Usuario paga en Systeme
↓
Systeme dispara webhook New sale
↓
Backend recibe /api/webhooks/systeme
↓
Backend valida firma
↓
Backend crea/actualiza customer_access
↓
Backend crea invite_token
↓
Backend guarda inviteUrl en Systeme
↓
Backend agrega tag RB_INVITE_READY
↓
Systeme manda email de acceso
↓
Usuario entra a /crear-cuenta?token=...
↓
Backend valida token
↓
Usuario crea cuenta
↓
Backend crea sesión
↓
Usuario entra al dashboard
Tablas usadas
customer_access
invite_tokens
users
user_sessions
user_channels
payment_events
Endpoints usados
POST /api/webhooks/systeme
GET /api/invites/validate?token=...
POST /api/auth/register-with-invite
POST /api/auth/login
GET /api/auth/me
Regla de acceso
customer_access.status = active => acceso permitido
customer_access.status = cancelled => acceso bloqueado
Cancelación

Si Systeme manda cancelación/reembolso:

customer_access.status pasa a cancelled
user_channels se bloquea
user_sessions se borra/invalida
usuario pierde acceso
Decisión Stripe

Stripe no se implementa en beta.

Motivo:

Systeme ya tiene checkout.
Systeme ya manda webhook.
El backend ya tiene customer_access e invite_tokens.
Agregar Stripe ahora duplicaría flujo de pagos.

Después validas con pruebas.

Checklist real:

```txt
1. Confirmar producto beta en Systeme.
2. Confirmar webhook New sale activo.
3. Hacer compra test o real.
4. Ver logs backend.
5. Confirmar customer_access.
6. Confirmar invite_tokens.
7. Confirmar que llegó email/link.
8. Crear cuenta con token.
9. Login.
10. Confirmar acceso al dashboard.

Comandos útiles en backend:

;
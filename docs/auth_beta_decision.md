# Decisión Auth Beta — RadarBallena

## Objetivo

Definir cómo entran usuarios reales a la beta sin romper la seguridad actual del backend.

## Decisión

Para la beta se reutiliza el backend productivo actual de auth/session.

No se implementa auth nuevo de Lovable en esta etapa.

La beta queda cerrada por invitación/acceso manual temporal.

Decisión elegida:

```txt
A. Reusar backend productivo actual de auth/session
+
C. Mantener beta cerrada con acceso manual temporal

Se descarta temporalmente:

B. Usar auth nuevo del frontend/Lovable
Motivo

El backend actual ya separa correctamente los tres tipos de acceso:

usuario frontend = sesión/cookie
worker interno = x-api-key / INTERNAL_API_KEY
admin = sesión normal con role admin

No conviene mezclar x-api-key con usuarios normales.

No conviene duplicar login/sesiones con Lovable Auth mientras el backend productivo ya controla usuarios, sesiones, invitaciones, canales, pagos y webhooks.

Flujo beta mínimo
Usuario paga o es aprobado manualmente.
Backend crea o activa customer_access.
Backend genera invite_token.
Usuario recibe link:
https://portal.radarballena.com/crear-cuenta?token=...
Frontend valida token contra:
GET https://app.radarballena.com/api/invites/validate?token=...
Usuario crea contraseña con:
POST https://app.radarballena.com/api/auth/register-with-invite
Backend crea usuario, liga acceso y crea sesión.
Frontend consume endpoints protegidos usando cookie de sesión.
Dominios

Frontend:

https://portal.radarballena.com

Backend/API:

https://app.radarballena.com

El frontend debe llamar al backend con cookies habilitadas:

credentials: "include"

El backend debe permitir explícitamente el origen:

https://portal.radarballena.com
CSRF

Se mantiene CSRF para rutas sensibles de usuario frontend.

No aplica igual para workers internos, porque workers usan:

x-api-key: INTERNAL_API_KEY
Customer Access

customer_access controla si un usuario puede entrar o no.

Estados esperados:

active
cancelled

Regla:

customer_access.active => puede crear/usar cuenta
customer_access.cancelled => bloquear acceso y sesiones
Registro público

El registro público no debe quedar abierto.

La única creación de cuenta válida para beta debe ser:

/register-with-invite

o pantalla equivalente:

/crear-cuenta?token=...
Lovable Auth

Lovable Auth no se usa para beta.

Razón:

duplicaría sesiones;
duplicaría permisos;
complicaría cookies entre portal y backend;
podría romper el modelo actual de admin, usuario y worker;
no controla customer_access, invite_tokens ni Systeme.
Mínimo viable para beta

Para lanzar beta cerrada se necesita:

login actual funcionando;
sesión/cookie funcionando entre portal.radarballena.com y app.radarballena.com;
customer_access activo para usuarios permitidos;
registro solo por invitación;
workers manteniendo x-api-key;
admins manteniendo sesión admin;
frontend nuevo usando credentials: "include".
Decisión final

Se reutiliza el backend productivo actual de auth/session.

La beta será cerrada por invitación o acceso manual temporal.

No se usa auth nuevo de Lovable hasta después de validar la beta.


Luego en Trello marcas así:

```txt
✅ Revisar login actual
✅ Revisar cookies/domains
✅ Revisar portal.radarballena.com vs app.radarballena.com
✅ Revisar CSRF
✅ Revisar si customer_access ya puede controlar acceso
✅ Decidir mínimo viable para beta

Y en Definition of Done:

✅ Decisión tomada
✅ Flujo de acceso beta definido
✅ No se mezclan usuario normal/session con x-api-key de workers

Después de crear el archivo, haz commit:

git add docs/auth_beta_decision.md
git commit -m "docs: define beta auth decision"
# Proposal: Kureha MVP — Plataforma operativa clinica gobernada

Kureha es la plataforma operativa de la clinica: multi-tenant, con autoservicio
del paciente, sincronizacion con Google Calendar, gestion operativa de personal,
RBAC por accion y copilot interno para staff — todo sobre un nucleo de gobernanza
(RLS, consentimiento versionado, auditoria append-only, HITL, validador de scope
clinico). Este documento (`openspec/`) es la fuente de verdad autocontenida del
producto.

> La plataforma agrega, sobre el nucleo de gobernanza, siete concerns de
> endurecimiento que la gobernanza de datos clinicos exige: **autenticacion de
> usuario (login)**, **gestion de sesion**, **capa de cache**, **rate limiting**,
> **idempotency keys** en el sync de Calendar, **observabilidad/alerting del
> hash-chain de auditoria** y **despliegue AWS** como constraint de MVP. Los
> items siguen el mismo patron "detras de puerto" ya establecido (nuevo
> `AuthPort`, coherente con `CalendarSyncPort`).

El chat del paciente y el copilot de staff se entregan a traves de un unico
asistente conversacional, **Tony**, con requisitos de experiencia de primera
clase: auto-descripcion de sus capacidades, memoria de corto plazo efimera por
sesion, respuestas en streaming con visibilidad de eventos, manejo de errores
descriptivo, guardrails de entrada y salida, y salida en Markdown. La topologia
de despliegue modela ademas un **frontend tier** explicito (SPA estatica)
separado del backend, sin API Gateway ni Redis — decisiones deliberadas de MVP
detalladas abajo.

## Intent

Las clinicas y consultorios en Peru operan hoy con herramientas fragmentadas:
agenda por telefono/WhatsApp manual, personal y turnos en hojas de calculo,
y cero trazabilidad de quien autorizo cada cambio. A la vez enfrentan una
obligacion legal creciente sobre dato de salud (dato sensible bajo Ley 29733,
trazabilidad de decisiones automatizadas bajo el reglamento de la Ley 31814,
riesgo de sancion SUSALUD). Ningun sistema generico de agenda ni ningun ERP
clinico ligero cubre esa gobernanza de fabrica.

Kureha entrega una **plataforma operativa** que nace auditable y gobernada, no
parcheada despues. El paciente gestiona sus citas por si mismo (web + chat
embebido) y ve reflejadas sus citas en su Google Calendar; el personal de la
clinica opera agenda, registro de personal y turnos desde un copilot interno
cuyas acciones dependen de sus permisos; y cada operacion — la ejecute un
humano o el agente — queda bajo RLS multi-tenant, consentimiento vigente y
bitacora inmutable. El exito del MVP es: una clinica multi-sede puede operar su
dia a dia (agenda + personal + turnos) desde Kureha, con autoservicio del
paciente y sync de calendario, sin que ninguna accion escape a la gobernanza.

## Scope

### In Scope

**Nucleo de gobernanza (se preserva, se extiende a tenant):**
- RLS a nivel de BD por **tenant + sede + rol**; deny-by-default; el agente nunca opera con `BYPASSRLS`.
- Consentimiento informado versionado como precondicion de todo procesamiento de dato del paciente.
- `audit_logs` append-only (hash-chain ligero) desde el dia uno: actor, timestamp, motivo, aprobacion.
- HITL obligatorio para acciones de alto riesgo (cancelacion masiva, cambio de profesional distinto al solicitado, y las que la clinica marque de alto riesgo por config).
- Validador de scope clinico: el agente orienta administrativamente pero **nunca diagnostica ni interpreta sintomas**; ante ambiguedad, escala. Esta linea no se mueve.

**Plataforma operativa (nuevo):**
- **Multi-tenant**: `tenant` = organizacion cliente (negocio de clinica) con N sedes. `tenant_id` como capa de aislamiento por encima de `site_id`; RLS scopea por ambos.
- **Portal de autoservicio del paciente**: el paciente gestiona sus propias citas via flujos web tradicionales (formularios) **y** via un chat embebido en el portal. Ambos son canales de entrada a los mismos casos de uso de dominio.
- **Chat embebido del paciente**: mismo motor de chat, orientado al paciente; recomienda y orienta (sugiere horarios alternativos, recuerda que llevar a la cita, orienta sobre el proceso administrativo) dentro del guardrail clinico duro.
- **Sincronizacion con Google Calendar (en MVP, detras de puerto)**: `CalendarSyncPort` con OAuth2 por paciente usando su email registrado; espeja create/reprogramar/cancelar hacia su Google Calendar. Es un **efecto best-effort**: si la Google API falla, la cita dentro de Kureha igual se confirma (la sincronizacion no es requisito bloqueante).
- **Gestion operativa de personal (solo operativa, NO HR completo)**: registro de personal (altas/bajas) y horarios/turnos por profesional y por sede.
- **RBAC por accion**: la autorizacion se evalua a nivel de **accion concreta**, configurable por clinica (p.ej. "recepcion puede reprogramar pero no cancelar sin aprobacion" como regla configurable). Los roles siguen existiendo como agrupacion, pero los chequeos de autorizacion son action-level, no solo role-level.
- **Copilot interno para staff**: mismo motor de chat que el del paciente, pero las herramientas/acciones que expone dependen de los permisos de accion del usuario autenticado (recepcion, profesional y admin ven capacidades distintas, todas gobernadas por el mismo RBAC por accion).

**Experiencia conversacional del asistente (Tony):**

El chat del paciente y el copilot de staff comparten motor y se presentan como
un asistente llamado **Tony**. La calidad de esa conversacion es parte del scope
de MVP, no un pulido posterior: define como responde, que recuerda, como falla y
que no puede ser inducido a hacer.

- **Identidad del asistente: "Tony"** — el chat del paciente y el copilot de
  staff se presentan como Tony. Tony puede responder sobre sus propias
  capacidades cuando el usuario pregunta (auto-descripcion de lo que puede y no
  puede hacer), en coherencia con el guardrail clinico duro: Tony explica que
  **recomienda y orienta administrativamente pero nunca diagnostica**. Rationale:
  un asistente con nombre y con una descripcion honesta de sus limites reduce
  expectativas erroneas del paciente (no es un medico) y refuerza el limite de
  scope desde el propio discurso del asistente. Toca: `embedded-patient-chat`,
  `internal-staff-copilot`, `clinical-safety`.

- **Memoria de corto plazo, efimera por sesion (se limpia al refrescar)** — Tony
  recuerda la conversacion multi-turno dentro de una sesion, pero un refresh
  (F5/reload) limpia esa memoria: el usuario empieza de cero. Mecanismo (ya
  cubierto por el design, no se introduce uno nuevo): el `PostgresSaver` (ADR-7)
  ya persiste el estado de la conversacion keyed por `thread_id`. La frontera es
  que el `thread_id` se genera en el cliente y vive **solo en estado en memoria
  del frontend** (p.ej. React state), **nunca** en `localStorage`/
  `sessionStorage`/cookies. Un refresh pierde ese valor en memoria, el frontend
  solicita un `thread_id` nuevo y Tony no tiene continuidad desde la perspectiva
  del usuario — mientras el checkpoint del thread anterior **permanece en
  Postgres para auditoria** (coherente con el core de auditoria/gobernanza). No
  requiere Redis ni store nuevo. Requisito explicito: **el frontend nunca
  persiste `thread_id` entre reloads**. Toca: `embedded-patient-chat`,
  `internal-staff-copilot`; referencia ADR-7.

- **Respuestas en streaming con visibilidad de estado/eventos** — las respuestas
  de Tony y del copilot se transmiten en **streaming** (no esperan la respuesta
  completa) **y** exponen estado/eventos intermedios mientras el agente trabaja
  (p.ej. "consultando disponibilidad", "buscando tus citas", indicador de
  tool-call en progreso) — no solo el stream de tokens final, sino visibilidad de
  lo que el agente esta haciendo a mitad de turno. Rationale: contencion de la
  percepcion de latencia y confianza (el usuario ve que el agente esta actuando,
  no colgado). Aplica a `embedded-patient-chat` e `internal-staff-copilot`.

- **Manejo de errores descriptivo y especifico** — los errores que se muestran al
  usuario deben ser **especificos y con contexto preciso**, no fallos genericos u
  opacos. Requiere una **taxonomia de errores** (validacion, auth,
  calendar-sync degradado — best-effort per `google-calendar-sync`, HITL
  pendiente, scope clinico rechazado, rate-limited) mapeada cada uno a un mensaje
  claro y **no filtrante** (sin stack traces internos ni secretos). Rationale: un
  error preciso es accionable para el usuario y no expone superficie interna;
  encaja con la postura de gobernanza (no filtrar) y con el best-effort del sync
  (un fallo de Calendar se comunica como "sync degradado", no como error
  bloqueante). Toca: `embedded-patient-chat`, `internal-staff-copilot`,
  `platform-hardening`; se relaciona con `google-calendar-sync`, `clinical-safety`
  y el rate limiting.

- **Guardrails sobre los chats (entrada + salida)** — mas alla del guardrail de
  scope clinico existente (recomienda/orienta, nunca diagnostica), se agrega
  **resistencia a prompt injection / jailbreak** y enforcement que aplica a la
  **entrada** (lo que el usuario envia) **y** a la **salida** (lo que Tony/el
  copilot emiten) — no solo una instruccion en el system prompt. El mecanismo se
  mantiene **proporcionado a un MVP** (no se especifica aca un producto de
  guardrails pesado de terceros — esa es una decision de `sdd-design`), pero el
  **requisito** (enforcement entrada+salida, resistencia a injection, prevencion
  de fuga tenant/scope) pertenece al proposal/spec. Rationale: RLS y RBAC ya son
  el piso duro de datos y operaciones, pero una injection podria intentar torcer
  el discurso del asistente (cruzar scope clinico, exfiltrar contexto de otro
  tenant en la propia respuesta); el guardrail de entrada+salida cierra ese hueco
  a nivel de conversacion. Toca: `embedded-patient-chat`, `internal-staff-copilot`,
  `clinical-safety`, `platform-hardening`.

- **Respuestas formateadas en Markdown** — las respuestas de Tony y del copilot
  se renderizan como **Markdown** (encabezados, listas, negrita, bloques de
  codigo donde aplique), no texto plano. Rationale: legibilidad de respuestas
  administrativas frecuentemente estructuradas (opciones de horario, pasos,
  listas de que llevar). Toca: `embedded-patient-chat`, `internal-staff-copilot`.

**Endurecimiento de plataforma e infraestructura:**

El dominio operativo por si solo deja abiertos siete concerns de plataforma
que un sistema con dato clinico sensible **no** puede diferir. Cada uno indica su
impacto sobre puertos/specs existentes.

- **Autenticacion de usuario / login** — nuevo `AuthPort` (coherente con
  `CalendarSyncPort`). El sistema hoy tiene JWT con claims `tenant_id+site_id+role`
  pero **nunca definio como un usuario se autentica**. Debe soportar **email+password
  Y "Sign in with Google" (login federado)**. El login federado con Google es un
  concern **distinto** del OAuth de Google Calendar (ADR-11/12): un paciente puede
  loguearse con Google **y** por separado conectar su Calendar — cuentas, scopes y
  almacenes de token distintos; jamas se deben confundir. **Recomendacion (validada
  contra el design): IdP externo gestionado detras de `AuthPort`**, no auth
  roll-your-own en FastAPI. En un sistema cuyo diferencial es la gobernanza
  (RLS+audit+consent) la superficie de manejo de credenciales — hashing, rotacion,
  deteccion de brechas, MFA, anti brute-force — es el peor lugar para asumir
  responsabilidad propia; delegarla a un IdP maduro reduce la superficie de ataque
  sobre credenciales. El vendor concreto lo decide `sdd-design`; nota arquitectonica:
  **Supabase Auth es el mejor fit** por la centralidad de Postgres+RLS (emite claims
  hacia GUCs con friccion minima), con **Auth0/Clerk** como alternativas viables.
  Frontera clave: el IdP resuelve **authn** (quien sos); Kureha conserva el
  **authz context** (el mapeo `users` -> `tenant_id/site_id/role` sigue en su BD y
  se proyecta a los GUCs como hoy). Impacto: **nueva spec `user-authentication`**;
  toca `access-control` (origen del `request_ctx`).

- **Gestion de sesion** — hoy solo existe "Session Context Propagation"
  (claims JWT -> GUCs via `SET LOCAL`, en `access-control`). Falta el ciclo de vida:
  **expiry del access token, estrategia de refresh token, logout/revocacion**, y el
  manejo del **cambio de rol/permiso a mitad de sesion** (p.ej. admin desactiva a un
  staff con sesion activa). Tension a resolver: el rol viaja horneado en el token,
  pero RBAC se resuelve **vivo** contra la BD por request — access tokens de vida
  corta acotan la ventana de claim stale, y el estado `active` del usuario/staff se
  chequea por request (no desde el token) para matar sesiones de inmediato. Impacto:
  **nueva spec `session-management`**; interactua con `action-based-rbac`
  (resolucion viva) y reubica/extiende el requisito de propagacion de contexto de
  `access-control`.

- **Capa de cache** — ausente del design actual. **ADR-7 rechazo Redis SOLO
  para el checkpointer de LangGraph, no para un cache de queries/permisos** — esta es
  una decision **separada**, no re-litiga ADR-7. Candidatos a cachear: **lookups de
  disponibilidad de citas**, **resolucion RBAC accion-permiso** (hoy se recomputa por
  request en `ListAllowedActions`/`AuthorizeAction`), **resultados frecuentes de tools
  del copilot**. Constraint duro: el cache es **tenant-scoped**, **nunca** sirve una
  fila que RLS negaria, y la **invalidacion en cambio de permiso debe ser correcta**
  — un "allowed" cacheado tras un revoke seria un **bug de seguridad**, no de
  performance. Impacto: **nueva capacidad en spec `platform-hardening`**; toca
  `action-based-rbac` (semantica de invalidacion del cache de permisos).

- **Rate limiting** — sobre los **endpoints de auth** (anti brute-force /
  credential stuffing) y sobre el **endpoint de chat del paciente** (anti-abuso y
  contencion de costo LLM/DoS). Dimensiones por tenant + IP + usuario. Aun con IdP
  externo, los endpoints propios de Kureha (intercambio de token, chat) necesitan su
  propio limite. Impacto: **spec `platform-hardening`**; frontera inbound.

- **Idempotency keys en el sync de Calendar** — el sync es best-effort con
  reintentos (`attempts`), pero un retry de `events.insert` **puede duplicar el evento**
  en el calendario del paciente. Fix: clave de idempotencia / event id determinista
  (derivado de `appointment_id`) para que el reintento sea idempotente (upsert por
  clave, no insert nuevo). Impacto: **spec `google-calendar-sync`** + columna de clave
  de idempotencia en `calendar_sync`; addendum a ADR-11.

- **Observabilidad / alerting del hash-chain de auditoria** — hoy la
  integridad de la cadena no se monitorea: si se corrompe, **nadie se entera**. El job
  de verificacion (design 4.3) debe **emitir alarma ante tamper** y existir un
  **dead-man's switch** que verifique que el job efectivamente corre. Impacto: **spec
  `consent-and-audit`** (requisito de monitoreo de integridad) + design 4.3.

- **Despliegue AWS como concern de MVP** — target cloud = **AWS**, postura
  **"segura pero sin sobre-ingenieria"** (consciente de costo/complejidad, no escala
  enterprise multi-cuenta). La seguridad de infra **extiende el nucleo de gobernanza**
  (RLS, cifrado, auditoria) hacia la red: **aislamiento de red** (BD en subred
  privada), **gestion de secretos** (la KEK de ADR-12 vive en un secret manager real —
  AWS Secrets Manager/KMS — lo que **cierra una dependencia antes hand-waved**), **TLS
  en transito**, **IAM least-privilege**. Esto es un **requisito y sus constraints**,
  no una solucion: **NO** se disena aca la topologia concreta (VPC/ECS/RDS/etc.) — eso
  es trabajo de `sdd-design`. Impacto: **spec `platform-hardening`** (constraints de
  seguridad de infra); nuevo ADR de baseline de seguridad de despliegue. La
  topologia incorpora ademas tres precisiones de arquitectura, coherentes con el
  mismo mandato "seguro sin overkill":
    - **Frontend tier explicito**: el frontend es un componente propio del modelo
      de despliegue, no "Internet" pegado directo al ALB. Direccion recomendada (a
      formalizar en spec/design): **SPA estatica servida por hosting estatico +
      CDN (S3 + CloudFront)**, separada del tier de backend (ALB+WAF+ECS+RDS). No
      agrega compute nuevo — solo hosting estatico y CDN — y mantiene el frontend
      fuera de la superficie del backend. Es tambien donde vive, en memoria, el
      `thread_id` de la memoria efimera de Tony (nunca en storage persistente).
    - **API Gateway: explicitamente NO en MVP**. ALB+WAF ya cubre terminacion
      TLS, routing y rate limiting para el unico servicio de backend; no hay
      backend Lambda, ni composicion de multiples APIs, ni gestion de API
      keys/quotas de terceros. Decision deliberada, no un olvido. **Trigger de
      upgrade documentado**: si Kureha expone mas adelante una API publica
      partner-facing que requiera API keys/quotas por cliente independientes de
      las reglas IP del WAF, se reevalua — mismo patron anti-overkill que el resto
      del baseline.
    - **Redis: explicitamente NO en MVP**. Refuerza la decision existente
      (sin cache compartido). Ademas, la **memoria de corto plazo de Tony**
      tambien la cubre el `PostgresSaver` (checkpointer de ADR-7), **no** un cache
      nuevo: no hay infraestructura de cache compartido en el diagrama porque no
      existe. Se deja explicito para que no se lea como un hueco.

### Out of Scope (V2 — mismo patron "detras de puerto con stub", ya establecido)

- **Telegram como canal**: en MVP el unico canal es el chat web (embebido en portal y en copilot). Telegram es el segundo canal, se agrega despues sobre el mismo puerto de canal.
- `WaitlistAgent` y reasignacion automatica de cupos.
- Exportacion/consumo FHIR `Appointment` y sync con RENHICE/HCE.
- Panel de gobernanza / compliance y reportes SUSALUD.
- **HR completo**: nomina/planilla, contratos, evaluaciones de desempeño. La gestion de personal se mantiene **solo operativa** (registro + turnos) como se indica arriba.
- Conector WhatsApp Business API real y LangSmith productivo (se disena el puerto).

## Capabilities

### New Capabilities

**Gobernanza (nucleo no negociable):**
- `role-based-rls`: aislamiento a nivel de BD por **tenant + sede + rol**; resuelve *que filas ve* cada actor. Se complementa con `action-based-rbac`, que resuelve *que operaciones puede ejecutar*.
- `versioned-consent`: registro y verificacion de consentimiento con version aceptada.
- `append-only-audit-log`: bitacora inmutable (hash-chain) de cada accion.
- `clinical-scope-validator`: guardrail que impide diagnostico/interpretacion clinica.
- `appointment-scheduling`: triage + alta/reprogramacion/cancelacion con disponibilidad.
- `appointment-reminders`: confirmaciones y recordatorios sobre canal abstracto.
- `human-in-the-loop-approval`: interrupt de aprobacion para acciones de alto riesgo.

**Plataforma operativa:**
- `multi-tenant-isolation`: capa `tenant_id` por encima de `site_id`; RLS scopea por tenant + sede + rol.
- `patient-self-service-portal`: gestion de citas por el propio paciente via flujos web tradicionales.
- `embedded-patient-chat`: chat embebido en el portal como canal alterno a los formularios web, sobre los mismos casos de uso; presentado como el asistente **Tony** (auto-descripcion de capacidades, memoria de corto plazo efimera por sesion, streaming con visibilidad de eventos, respuestas en Markdown, guardrails de entrada+salida).
- `google-calendar-sync`: `CalendarSyncPort` (OAuth2 por paciente, best-effort) que espeja create/reprogramar/cancelar en Google Calendar.
- `staff-registry`: registro operativo de personal (altas/bajas) por sede.
- `staff-scheduling`: horarios/turnos por profesional y por sede.
- `action-based-rbac`: autorizacion por accion concreta, configurable por clinica; roles como agrupacion, chequeos action-level.
- `internal-staff-copilot`: chat interno (mismo asistente **Tony**) cuyo toolset depende de los permisos de accion del usuario autenticado; comparte la experiencia conversacional (streaming con eventos, memoria efimera, Markdown, guardrails entrada+salida).

**Plataforma / infraestructura:**
- `user-authentication`: login por email+password y por "Sign in with Google" (federado) detras de `AuthPort`; IdP externo gestionado (authn), con el mapeo a `tenant_id/site_id/role` conservado en Kureha (authz).
- `session-management`: ciclo de vida de sesion (expiry, refresh, logout/revocacion) y manejo de cambio de rol/permiso a mitad de sesion.
- `query-and-permission-cache`: cache tenant-scoped de disponibilidad, resolucion RBAC y tools del copilot, con invalidacion correcta ante cambio de permiso (decision separada de ADR-7).
- `rate-limiting`: limites en endpoints de auth y de chat del paciente (anti brute-force y anti-abuso/costo).
- `calendar-sync-idempotency`: clave de idempotencia / event id determinista para reintentos de Calendar sin duplicar eventos.
- `audit-integrity-monitoring`: alerting de tamper del hash-chain + dead-man's switch del job de verificacion.
- `conversational-assistant-experience`: identidad del asistente **Tony** (chat de paciente + copilot de staff) con auto-descripcion de capacidades; memoria de corto plazo efimera por sesion (`thread_id` en memoria del cliente sobre el `PostgresSaver`, se limpia al refrescar); streaming de respuestas con visibilidad de estado/eventos; salida en Markdown.
- `chat-guardrails-and-errors`: guardrails de entrada+salida sobre los chats (resistencia a prompt injection/jailbreak, prevencion de fuga tenant/scope, proporcionado a MVP) y taxonomia de errores descriptivos no-filtrantes mapeados a mensajes claros.
- `secure-aws-deployment`: baseline de despliegue AWS que extiende la gobernanza a infra (aislamiento de red, secret manager para la KEK, TLS, IAM least-privilege) — constraints, no topologia; incluye un **frontend tier** explicito (SPA estatica separada del backend, direccion S3+CloudFront) y las decisiones deliberadas **sin API Gateway** y **sin Redis** en MVP.

## Approach

Se mantiene el grafo LangGraph supervisor + especialistas con `interrupt()` para
HITL sobre un dominio aislado (candidato hexagonal, se confirma en design), y
Postgres con RLS como fuente de verdad de *visibilidad de datos*. La extension
de scope se apoya en cuatro decisiones de forma:

1. **Aislamiento multi-tenant via RLS + `tenant_id`, NO schema-per-tenant.**
   Se agrega `tenant_id` a las tablas operativas y a las variables de sesion
   (`SET LOCAL app.tenant_id`), y las policies scopean por `tenant_id` +
   `site_id` + rol. Rationale: schema-per-tenant multiplica migraciones,
   complica el pooling y el reporting cross-sede, y no aporta aislamiento
   adicional real frente a RLS deny-by-default bien testeada. Un solo esquema
   con RLS por tenant es el patron multi-tenant estandar y mantiene las policies
   declarativas.

2. **Autorizacion en dos planos: RLS (datos) + RBAC por accion (operaciones).**
   RLS sigue decidiendo *que ve* cada actor; una capa de permisos por accion
   (tabla de permisos configurable por tenant, evaluada en el dominio antes de
   ejecutar cada caso de uso) decide *que puede hacer*. El copilot interno y el
   chat del paciente derivan su toolset de esos permisos: una accion no ofrecida
   por permiso no existe para ese usuario. Roles quedan como plantillas de
   permisos, no como capacidades hardcodeadas.

3. **Google Calendar como efecto best-effort detras de `CalendarSyncPort`.**
   El caso de uso de agenda confirma la cita en Kureha en su transaccion (con
   auditoria), y *luego* emite hacia `CalendarSyncPort` como efecto no
   transaccional. Un fallo de la Google API se registra (audit + estado de sync
   pendiente/fallido) pero NO revierte la cita ni bloquea al paciente. Rationale
   explicito del negocio: la fuente de verdad es Kureha; el calendario es una
   comodidad espejada, no un sistema de registro.

4. **Un solo canal en MVP (chat web) sobre un puerto de canal.** El chat
   embebido del paciente y el copilot de staff comparten motor; ambos entran por
   el mismo puerto de canal que en V2 recibira Telegram y WhatsApp. Esto evita
   reescritura al sumar canales y mantiene el guardrail de scope clinico en un
   unico punto, independiente del canal.

5. **Autenticacion delegada a IdP externo tras `AuthPort`; authz retenido en Kureha.**
   El login (email+password y Google federado) se resuelve contra un IdP
   gestionado detras de un nuevo puerto `AuthPort`, espejo de `CalendarSyncPort`. La
   frontera es deliberada: el IdP responde **authn** (probar identidad); Kureha
   conserva el **authz context** — el `users` row sigue mapeando identidad ->
   `tenant_id/site_id/role`, y ese contexto se proyecta a los GUCs de Postgres
   exactamente como hoy (`SET LOCAL`). Rationale: en un sistema cuyo valor es la
   gobernanza de dato clinico, poseer la maquinaria de credenciales (hashing,
   rotacion, MFA, anti brute-force, respuesta a brechas) agrega superficie de ataque
   de alta responsabilidad sin diferencial; un IdP maduro la absorbe. Tradeoffs
   asumidos: dependencia de vendor, costo por MAU, y la necesidad de sincronizar la
   identidad del IdP con el `users` de Kureha (mitigado: la identidad es la clave, el
   authz vive en Kureha). El login federado con Google **no** reutiliza el OAuth de
   Calendar: son integraciones Google distintas, con scopes y almacenes de token
   separados. Vendor concreto y ciclo de vida de token: `sdd-design`.

6. **Experiencia conversacional (Tony) sobre la infraestructura ya decidida, sin
   piezas nuevas.** La memoria de corto plazo efimera **no** introduce un store:
   reusa el `PostgresSaver` (ADR-7) keyed por `thread_id`, y mueve la frontera al
   cliente — el `thread_id` vive solo en memoria del frontend, nunca en storage
   persistente, asi un refresh genera un `thread_id` nuevo y corta la continuidad
   visible (el checkpoint anterior queda en Postgres solo para auditoria). El
   streaming y la visibilidad de eventos se apoyan en el streaming nativo del
   grafo; los guardrails de entrada+salida extienden el validador de scope
   clinico ya presente (que ya opera inbound y outbound) sumando resistencia a
   injection y anti-fuga tenant/scope, con RLS/RBAC como piso duro por debajo; y
   la taxonomia de errores traduce fallos de dominio/infra (auth, sync degradado,
   HITL pendiente, scope rechazado, rate-limited) a mensajes no-filtrantes.
   Rationale: la calidad conversacional es requisito de MVP, pero se logra
   endureciendo y exponiendo lo que ya existe, no agregando infraestructura —
   coherente con el mandato "seguro sin overkill".

Canales y externos diferidos (Telegram, WhatsApp, LangSmith, FHIR) quedan detras
de puertos con adaptadores stub, coherente con el patron ya establecido.

## Affected Areas

| Area | Impacto | Descripcion |
|------|---------|-------------|
| `openspec/specs/*` | New | access-control, consent-and-audit, clinical-safety, appointment-scheduling, multi-tenant-isolation, patient-self-service-portal, embedded-patient-chat, google-calendar-sync, staff-registry, staff-scheduling, action-based-rbac, internal-staff-copilot. |
| BD — esquema operativo | New | `patients`, `appointments`, `availability`, `consents`, `audit_logs` con `tenant_id` + RLS por tenant+sede+rol; `tenants`, `action_permissions`/`role_permissions` (RBAC), `staff_members`/`shifts` (staff), `calendar_sync` (estado OAuth + sync por paciente). |
| Grafo LangGraph | New | Toolset dinamico por permisos de accion; nodo/efecto de `CalendarSyncPort`; canal web como inbound. |
| Autorizacion | New | Capa RBAC por accion (evaluacion en dominio) sobre RLS. |
| Portal paciente (web + chat) | New | Inbound adapters: formularios web + chat embebido hacia los mismos casos de uso. |
| Integracion Google Calendar | New | `CalendarSyncPort` + adaptador OAuth2 por paciente (best-effort). |
| FastAPI + JWT | New | Claims `tenant_id` + `site_id` + rol proyectados a GUCs; scopes por accion. |
| Autenticacion | New | `AuthPort` + adaptador de IdP externo (email+password y Google federado); mapeo identidad -> `users` -> GUCs. Toca `access-control`; nueva spec `user-authentication`. |
| Sesion | New | Ciclo de vida de token (expiry/refresh/logout/revocacion) + cambio de rol a mitad de sesion. Nueva spec `session-management`; extiende Session Context Propagation de `access-control`. |
| Cache | New | Cache tenant-scoped (disponibilidad, RBAC, tools) con invalidacion correcta; decision separada de ADR-7. Toca `action-based-rbac`; nueva capacidad en `platform-hardening`. |
| Rate limiting | New | Limites en endpoints de auth y chat del paciente. `platform-hardening`; frontera inbound. |
| Calendar sync — idempotencia | New | Clave de idempotencia / event id determinista; +columna en `calendar_sync`. Toca `google-calendar-sync`; addendum ADR-11. |
| Auditoria — observabilidad | New | Alerting de tamper del hash-chain + dead-man's switch del job. Toca `consent-and-audit` y design 4.3. |
| Despliegue AWS | New | Constraints de seguridad de infra (red privada, secret manager para KEK, TLS, IAM least-privilege) + **frontend tier explicito** (SPA estatica separada, direccion S3+CloudFront), **sin API Gateway** y **sin Redis** (decisiones deliberadas de MVP, con trigger de upgrade). Nueva spec `platform-hardening`; ADR-20 de baseline. NO topologia concreta (eso es design). |
| Experiencia de chat (Tony) | New | Identidad Tony + auto-descripcion de capacidades; memoria de corto plazo efimera (`thread_id` en memoria del cliente sobre `PostgresSaver`, se limpia al refrescar); streaming con visibilidad de eventos; respuestas en Markdown. Toca `embedded-patient-chat`, `internal-staff-copilot`, `clinical-safety`; referencia ADR-7. |
| Guardrails de chat | New | Resistencia a prompt injection/jailbreak, enforcement entrada+salida, prevencion de fuga tenant/scope; proporcionado a MVP. Toca `embedded-patient-chat`, `internal-staff-copilot`, `clinical-safety`, `platform-hardening`. |
| Manejo de errores | New | Taxonomia de errores (validacion, auth, calendar-sync degradado, HITL pendiente, scope rechazado, rate-limited) mapeada a mensajes claros y no-filtrantes. Toca `embedded-patient-chat`, `internal-staff-copilot`, `platform-hardening`. |
| Frontend tier / CDN | New | SPA estatica separada del backend (direccion S3+CloudFront); sin nuevo compute. Aloja el `thread_id` en memoria (memoria efimera de Tony). Toca despliegue AWS, `platform-hardening`. |

## Risks

| Riesgo | Prob. | Mitigacion |
|--------|-------|------------|
| **Aislamiento multi-tenant roto**: una policy que olvida `tenant_id` filtra datos entre clinicas | Med-Alta | Deny-by-default + `FORCE RLS`; `tenant_id` obligatorio en toda policy; suite de tests de aislamiento cross-tenant y cross-sede antes de datos reales; revision de policy checklist en design. |
| **Google Calendar OAuth / seguridad de tokens**: tokens de refresco por paciente son secretos de larga vida; fuga = acceso al calendario del paciente | Alta | Tokens cifrados at-rest; scope OAuth minimo (solo calendar events); `CalendarSyncPort` aislado; rotacion/revocacion; el fallo de sync no bloquea (superficie de ataque acotada). Detalle en design. |
| **Complejidad de RBAC por accion**: permisos configurables por clinica pueden dejar huecos (accion sin permiso definido = ambiguo) o contradecir RLS | Med-Alta | Deny-by-default tambien en RBAC (accion sin permiso => denegada); matriz permiso x accion versionada; RBAC nunca amplia lo que RLS niega (RLS es piso duro); tests de la capa de permisos. |
| **Sync best-effort deja calendario desincronizado** del estado real de Kureha | Med | Estado de sync explicito (`pendiente/ok/fallido`) + reintentos; Kureha es fuente de verdad; job de reconciliacion diferible a V2. |
| RLS mal configurada expone PII entre sedes/roles (riesgo previo, ahora con tenant) | Med | Tests de aislamiento por tenant/sede/rol; deny-by-default. |
| Auditoria con huecos deja accion sin traza | Med | Auditoria en la misma transaccion que la accion; write obligatorio. |
| Agente responde fuera de scope (cuasi-diagnostico) al recomendar y orientar | Med-Alta | Guardrail de scope duro antes de responder; el chat orienta administrativamente pero jamas clinicamente; corpus de mensajes limite en tests; escala ante duda. |
| Alcance MVP se infla mas alla de lo definido | Med | Out of Scope explicito: Telegram, WaitlistAgent, FHIR, panel, HR completo fuera. |
| **Cache de permisos stale**: un "allowed" cacheado tras un revoke deja actuar a un usuario sin permiso — bug de seguridad, no de performance | Alta | Invalidacion explicita del cache en cambio de `role_permissions`/`user_permissions` (o TTL muy corto); cache tenant-scoped; RLS sigue siendo piso duro (el cache nunca sirve una fila que RLS negaria); tests de invalidacion. |
| **Login federado confundido con OAuth de Calendar**: mezclar el token de "Sign in with Google" con el de Calendar filtra scope o rompe la separacion de concerns | Med-Alta | Dos integraciones Google separadas por diseno: `AuthPort` (authn) vs `CalendarSyncPort` (efecto), scopes y almacenes de token distintos; jamas se reusa un token entre ambos. |
| **Sesion no revocada a tiempo**: staff desactivado conserva sesion activa con rol horneado en el token | Med-Alta | Access tokens de vida corta (ventana acotada) + chequeo vivo de `active` por request (no desde el token) + lista de revocacion para kill inmediato; RBAC se resuelve vivo contra la BD. |
| **Reintento de Calendar duplica eventos** en el calendario del paciente | Med | Idempotency key / event id determinista (upsert por clave); el retry no crea, actualiza. |
| **Corrupcion del hash-chain sin deteccion**: nadie se entera si la cadena de auditoria se altera | Med-Alta | Job de verificacion con alarma de tamper + dead-man's switch que confirma que el job corre; la integridad deja de ser silenciosa. |
| **Superficie de infra AWS mal endurecida**: BD/secretos expuestos anulan la gobernanza a nivel de datos | Med-Alta | Baseline "seguro sin sobre-ingenieria": BD en subred privada, KEK en secret manager (no en la BD ni en env plano), TLS obligatorio, IAM least-privilege; el design fija la topologia concreta. |
| **Rate limiting insuficiente**: brute-force en login o abuso de costo LLM en el chat del paciente | Med | Limites por tenant+IP+usuario en endpoints de auth y chat; el IdP aporta defensa parcial pero los endpoints propios llevan su limite. |
| **Sobre-ingenieria de infra/auth** contradice el mandato "seguro pero sin overkill" e infla costo/complejidad | Med | Constraint explicito de proposal: no multi-cuenta enterprise, no microservicios; IdP gestionado en vez de plataforma propia; el design justifica cada pieza contra costo. |
| **`thread_id` persistido en el cliente rompe la memoria efimera**: si el frontend lo guardara en `localStorage`/cookie, un refresh reanudaria la conversacion (viola el requisito efimero) o otro usuario del mismo navegador veria contexto ajeno | Med-Alta | Requisito duro: `thread_id` **solo** en memoria del frontend, nunca en storage persistente; refresh genera `thread_id` nuevo; el checkpoint previo queda en Postgres solo para auditoria; test de que no se escribe a storage. |
| **Prompt injection / jailbreak** tuerce el discurso del asistente (cruza scope clinico, intenta exfiltrar contexto de otro tenant en la respuesta) | Med-Alta | Guardrails de **entrada + salida**, no solo system prompt; resistencia a injection proporcionada a MVP; RLS/RBAC como piso duro (una injection no excede lo que datos/operaciones permiten); el `response_guard` de scope outbound ya existe. |
| **Errores opacos** filtran internals (stack traces/secretos) o dejan al usuario sin accion | Med | Taxonomia de errores mapeada a mensajes claros y **no-filtrantes**; nunca se emite traza interna al usuario; el sync degradado se comunica como estado, no como fallo bloqueante. |
| **Eventos de streaming filtran datos sensibles**: un evento de progreso podria exponer PII o contexto de otro tenant | Med | Los eventos de estado son administrativos ("consultando disponibilidad"), sin PII clinica; pasan por el mismo RLS y por `response_guard`; los eventos nunca cruzan el `thread_id`/tenant del actor. |

## Rollback Plan

Cambios que tocan datos de paciente, personal o reglas de disponibilidad:
- Migraciones de esquema versionadas y reversibles (migrate down); nada de DDL manual. Incluye la migracion de `+tenant_id` y las tablas nuevas (RBAC, personal, turnos, calendar_sync).
- Feature flags por tenant/clinica para activar portal de autoservicio, copilot interno y sync de Google Calendar de forma independiente; desactivar revierte a operacion manual/asistida sin perder datos.
- `audit_logs` es append-only: no se borra; un rollback se registra como evento compensatorio, nunca como delete.
- Datos de consentimiento y auditoria se preservan siempre; un rollback de citas/turnos revierte estado operativo pero conserva la traza historica.
- **Google Calendar**: al ser best-effort, revertir la integracion no afecta la integridad de las citas en Kureha; se revoca el OAuth y se marca sync desactivado. Los tokens se eliminan/rotan en el rollback.
- Backup / point-in-time recovery de Postgres antes de cada migracion sobre tablas con PII o sobre `tenant_id`.

## Dependencies

- Postgres con soporte RLS. Runtime LangGraph/LangChain. FastAPI + JWT.
- **Credenciales Google Cloud (OAuth2 client)** para Calendar API — dependencia externa de negocio antes de `sdd-apply` del sync.
- Definicion de la **matriz inicial de permisos por accion** por rol/plantilla (input de negocio) antes de spec de `action-based-rbac`.
- Politica de consentimiento v1 (texto legal versionado) antes de spec del consent gate.
- Eleccion del **IdP externo** (Supabase Auth / Auth0 / Clerk) y credenciales del client de "Sign in with Google" (distinto del client de Calendar) antes de spec/design de `user-authentication`.
- Cuenta/target **AWS** y politica de gestion de secretos (Secrets Manager/KMS para la KEK de ADR-12) antes de design de despliegue.
- Decision de tecnologia de cache (Redis vs in-process) — la toma `sdd-design`; ADR-7 no la predetermina (aquel rechazo fue solo para el checkpointer).

## Success Criteria

- [ ] Una clinica multi-sede (un `tenant`, N sedes) opera agenda, personal y turnos desde Kureha sin fuga de datos entre tenants ni sedes (tests de aislamiento verdes).
- [ ] El paciente agenda/reprograma/cancela por si mismo via formulario web **y** via chat embebido, sobre los mismos casos de uso, sin doble reserva.
- [ ] Una operacion de agenda espeja en el Google Calendar del paciente cuando la API responde; si la Google API falla, la cita en Kureha igual se confirma y el fallo queda auditado (best-effort verificado).
- [ ] La autorizacion se evalua por accion: una regla configurada (p.ej. "recepcion no cancela sin aprobacion") se respeta sin cambiar codigo, y el toolset del copilot refleja los permisos del usuario.
- [ ] El copilot interno de staff expone acciones distintas segun el rol/permisos del usuario autenticado, todas gobernadas por RBAC por accion + RLS.
- [ ] Toda accion (humano o agente) queda en `audit_logs` append-only con actor, tenant, sede y motivo.
- [ ] Sin consentimiento vigente no se procesa dato del paciente.
- [ ] Cancelacion masiva y cambio de profesional se bloquean hasta aprobacion humana (HITL).
- [ ] El agente/chat orienta administrativamente pero **nunca** emite diagnostico; casos fuera de scope clinico escalan a humano.
- [ ] Un usuario se autentica por email+password **y** por "Sign in with Google"; el login federado es independiente de la conexion de Google Calendar (scopes/tokens separados).
- [ ] El access token expira; existe refresh, logout y revocacion; al desactivar a un staff con sesion activa, su siguiente request queda sin permisos (chequeo vivo, no desde el token).
- [ ] El cache acelera disponibilidad/RBAC/tools sin servir jamas una fila que RLS negaria; tras revocar un permiso, el cache no sigue autorizando la accion (test de invalidacion verde).
- [ ] Los endpoints de auth y de chat del paciente aplican rate limiting (brute-force y abuso de costo contenidos).
- [ ] Un reintento del sync de Calendar no duplica el evento del paciente (idempotencia verificada).
- [ ] La corrupcion del hash-chain dispara una alarma de tamper y el dead-man's switch detecta si el job de verificacion deja de correr.
- [ ] El despliegue en AWS cumple el baseline: BD en subred privada, KEK en secret manager (no en la BD ni en env plano), TLS en transito, IAM least-privilege — sin sobre-ingenieria enterprise.
- [ ] El chat se presenta como **Tony** y, ante una pregunta sobre sus capacidades, describe lo que puede y no puede hacer (recomienda/orienta administrativamente, nunca diagnostica).
- [ ] Tony mantiene contexto multi-turno dentro de una sesion; un refresh de pagina limpia la memoria (nuevo `thread_id`) y el usuario empieza de cero, mientras el checkpoint anterior permanece auditable en Postgres; el frontend no persiste `thread_id` entre reloads.
- [ ] Las respuestas de Tony y del copilot se transmiten en streaming y muestran estado/eventos intermedios (p.ej. "consultando disponibilidad") ademas del texto final.
- [ ] Un error mostrado al usuario es especifico segun su tipo (validacion, auth, calendar-sync degradado, HITL pendiente, scope rechazado, rate-limited) y nunca filtra stack traces ni secretos.
- [ ] Los chats resisten intentos de prompt injection/jailbreak con enforcement de entrada y salida; una injection no excede lo que RLS/RBAC permiten ni cruza tenant/scope.
- [ ] Las respuestas de Tony y del copilot se renderizan como Markdown.
- [ ] El despliegue modela un **frontend tier** explicito (SPA estatica separada del backend); sin API Gateway ni Redis en MVP (ALB+WAF cubre TLS/routing/rate limiting; la memoria de Tony la cubre el `PostgresSaver`).

## Mapa de especificaciones y diseno afectados

`sdd-spec` y `sdd-design` derivan de este proposal. Boundaries de spec:

| Artefacto | Accion | Motivo |
|-----------|--------|--------|
| `specs/user-authentication` | **NEW** | Login email+password + Google federado; `AuthPort`; frontera con IdP externo. |
| `specs/session-management` | **NEW** | Ciclo de vida de token (expiry/refresh/logout/revocacion) + cambio de rol/permiso a mitad de sesion. |
| `specs/platform-hardening` | **NEW** | Cross-cutting: rate limiting (auth+chat), requisitos de la capa de cache (candidatos, tenant-scope, invalidacion), constraints de seguridad del despliegue AWS, **taxonomia de errores no-filtrantes**, **guardrails de chat (injection, fuga tenant/scope)**, **frontend tier** (SPA separada) y decisiones **sin API Gateway** / **sin Redis**. |
| `specs/embedded-patient-chat` | **UPDATE** | Identidad Tony + auto-descripcion; memoria de corto plazo efimera (`thread_id` en memoria del cliente, se limpia al refrescar); streaming con visibilidad de eventos; respuestas en Markdown; guardrails entrada+salida; errores descriptivos. |
| `specs/internal-staff-copilot` | **UPDATE** | Misma experiencia conversacional (Tony) para el copilot: streaming con eventos, memoria efimera, Markdown, guardrails entrada+salida, errores descriptivos. |
| `specs/clinical-safety` | **UPDATE** | Tony auto-describe el limite recomienda/orienta vs diagnostica; los guardrails de injection refuerzan el scope outbound ya existente. |
| `specs/access-control` | **UPDATE** | El `request_ctx` nace de una identidad autenticada (upstream); frontera authn (nueva spec) vs proyeccion a GUCs (se queda aca). |
| `specs/action-based-rbac` | **UPDATE** | Semantica de invalidacion del cache de permisos; interaccion con cambio de permiso a mitad de sesion (resolucion viva). |
| `specs/google-calendar-sync` | **UPDATE** | Requisito de idempotencia en reintentos (event id determinista); +columna de clave en `calendar_sync`. |
| `specs/consent-and-audit` | **UPDATE** | Requisito de monitoreo de integridad del hash-chain: alerting de tamper + dead-man's switch. |
| `design.md` — stack table (1) | Referencia | Filas: IdP/`AuthPort`, cache (Redis vs in-process), rate limiter, secret manager AWS para la KEK. |
| `design.md` — RLS/SET LOCAL (4.2) | Referencia | El origen del contexto de request es una identidad autenticada upstream. |
| `design.md` — audit hash-chain (4.3) | Referencia | Alerting + dead-man's switch concretos. |
| `design.md` — RBAC (5) | Referencia | `ListAllowedActions`/`AuthorizeAction` recomputados por request -> candidatos a cache; addendum de invalidacion a ADR-10. |
| `design.md` — Calendar (7) | Referencia | Idempotencia de reintentos; addendum a ADR-11; la KEK de ADR-12 se ata a AWS Secrets Manager/KMS. |
| `design.md` — secciones + ADRs | Referencia | Authn/`AuthPort` + adaptador IdP; ciclo de sesion; capa de cache; rate limiting; observabilidad de auditoria; baseline de despliegue AWS. ADRs: ADR-14 (IdP externo + `AuthPort`), ADR-15 (ciclo de token/sesion), ADR-16 (cache + invalidacion), ADR-17 (rate limiting), ADR-18 (idempotencia Calendar), ADR-19 (alerting de auditoria), ADR-20 (baseline seguridad AWS). |
| `design.md` — grafo/estado (8) + ADR-7 | Referencia | Streaming con visibilidad de eventos sobre el streaming nativo del grafo; memoria efimera via `PostgresSaver` keyed por `thread_id` (ADR-7), con el `thread_id` generado y retenido en memoria del cliente (nunca persistido). |
| `design.md` — scope guard (8.2/8.3) | Referencia | Guardrails de chat entrada+salida: resistencia a injection y anti-fuga tenant/scope como refuerzo del `response_guard` de scope outbound; RLS/RBAC piso duro. |
| `design.md` — topologia AWS (20) + ADR-16/ADR-20 | Referencia | Frontend tier explicito (SPA estatica, direccion S3+CloudFront); **API Gateway NO** en MVP (ALB+WAF cubre TLS/routing/rate limiting; trigger de upgrade documentado); **Redis NO** (refuerza ADR-16; memoria de Tony via `PostgresSaver`); diagrama a actualizar con el frontend tier. |

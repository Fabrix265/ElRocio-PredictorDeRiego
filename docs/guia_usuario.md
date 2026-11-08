# Guía de usuario · Sistema de Plan de Riego

Grupo El Rocío (AvoPeru y Talsa) · fundo ENSUEÑO 1 · módulo EN01-MOD5

Esta guía explica cómo usar el sistema según tu rol. Cada función lleva una marca:

- **[Disponible]**: ya se puede usar (fase 1).
- **[Fase N]**: llega en una próxima fase. En el menú ya aparece, con el aviso «Disponible en la
  fase N», y esta guía la describe como está prevista en la propuesta.

Todas las fechas y horas del sistema están en **hora de Lima**.

## Contenido

1. [Roles y pantallas](#roles-y-pantallas)
2. [Para todos los roles](#para-todos-los-roles): ingresar, contraseñas, fundo y módulo
3. [El flujo diario completo](#el-flujo-diario-completo)
4. [Qué hace cada rol](#qué-hace-cada-rol): administrador, encargado, programador, subgerente
5. [Usuarios](#usuarios-solo-administrador) (solo administrador)
6. [Auditoría](#auditoría-administrador-y-subgerente) (administrador y subgerente)
7. [Qué trae cada fase](#qué-trae-cada-fase)

---

## Roles y pantallas

| Rol | Qué hace en el sistema |
|---|---|
| **Administrador** | Gestiona los usuarios y revisa la auditoría. Ve todas las pantallas y puede hacer todo lo del encargado. |
| **Encargado** | Genera los cronogramas de riego, los corrige y los publica, y registra el riego aplicado. |
| **Programador** | Ve los cronogramas publicados, los programa en campo y confirma el «Visto». |
| **Subgerente** | Revisa los cronogramas, solicita correcciones, edita el riego aplicado y revisa la auditoría. |

Pantallas del menú por rol:

| Pantalla | Administrador | Encargado | Programador | Subgerente | Disponible |
|---|---|---|---|---|---|
| Dashboard | ✔ | ✔ | ✔ (solo lo publicado) | ✔ | **[Disponible]** con tarjetas vacías; contenido en las fases 2 a 5 |
| Generar | ✔ | ✔ | — | — | [Fase 3] |
| Cronogramas | ✔ | ✔ edita | ✔ solo publicados, confirma Visto | ✔ lectura, solicita corrección | [Fase 3] lectura · [Fase 4] flujo |
| Riego aplicado | ✔ | ✔ edita y sube Excel | ✔ lectura | ✔ edita | [Fase 2] |
| Datos de campo | ✔ | ✔ | ✔ | ✔ | [Fase 5] |
| Auditoría | ✔ | — | — | ✔ | **[Disponible]** |
| Usuarios | ✔ | — | — | — | **[Disponible]** |

Si entras a una pantalla que tu rol no puede ver, el sistema muestra «No tienes acceso a esta
sección». Si crees que es un error, pide al administrador que revise tu rol. El servidor vuelve a
comprobar el permiso en cada acción; el menú solo oculta lo que no te corresponde.

---

## Para todos los roles

### Ingresar **[Disponible]**

1. Abre la dirección del sistema que te dio el administrador.
2. Escribe tu **usuario** y tu **contraseña** y toca **Ingresar**.
3. Si llegaste desde un enlace a una pantalla concreta (por ejemplo, desde un correo), después de
   ingresar vuelves a esa pantalla.

- Si el usuario o la contraseña no son correctos, verás «Usuario o contraseña incorrectos». Por
  seguridad, el mensaje es el mismo en los dos casos.
- Después de varios intentos fallidos el ingreso se bloquea unos minutos: «Demasiados intentos.
  Vuelve a intentarlo en N minutos.»
- La sesión se mantiene en ese navegador. Tendrás que volver a ingresar si pasas 7 días sin usar
  el sistema, o a los 30 días desde que ingresaste.
- Para salir, abre el menú con tu nombre (arriba a la derecha; en celular, **Menú** abajo) y
  elige **Cerrar sesión**. Cerrar sesión en una pestaña la cierra en todas las pestañas de ese
  navegador.
- Si el servidor no responde al abrir el sistema, verás «No se pudo conectar» con el botón
  **Reintentar**. Tu sesión no se pierde: reintenta cuando vuelva la conexión.

### Primer ingreso: crear tu contraseña **[Disponible]**

El administrador te da de alta con una **contraseña temporal**. La primera vez que ingreses, el
sistema te lleva a **Crea tu contraseña** y no te deja usar nada más hasta que la cambies:

1. En **Contraseña temporal**, escribe la que te dio el administrador.
2. Escribe tu **Nueva contraseña** y repítela.
3. Toca **Guardar contraseña**. Entrarás al sistema con la contraseña nueva.

La contraseña debe tener **entre 10 y 128 caracteres, con letras y números**, y no puede ser igual
a tu usuario. La lista bajo el campo marca cada requisito a medida que lo cumples.

### Cambiar tu contraseña **[Disponible]**

1. Abre el menú con tu nombre y elige **Cambiar contraseña**.
2. Escribe la contraseña actual y la nueva dos veces.
3. Guarda. Se cierran tus sesiones en otros dispositivos; en el que estás sigues dentro.

Si te equivocas en la contraseña actual varias veces seguidas, el sistema cierra todas tus sesiones
por seguridad y tendrás que volver a ingresar.

### Olvidé mi contraseña **[Disponible]**

1. En la pantalla de ingreso, toca **¿Olvidaste tu contraseña?**
2. Escribe tu usuario o tu correo y toca **Enviar enlace**.
3. Revisa tu correo (también la carpeta de correo no deseado) y toca **Restablecer contraseña**.
   El enlace es de **un solo uso** y vence en poco tiempo (30 minutos con la configuración
   por defecto).
4. Escribe la nueva contraseña dos veces y toca **Guardar contraseña**. Se cierran todas tus
   sesiones abiertas; ingresa de nuevo con la contraseña nueva.

- El sistema siempre responde «Si el usuario existe, enviaremos un enlace a su correo», exista o
  no el usuario, para no revelar quién tiene cuenta.
- Si el enlace venció o ya se usó, verás «El enlace no es válido o ya venció» y podrás pedir uno
  nuevo.
- Si tu usuario está desactivado, el correo no llegará: habla con el administrador.
- Si no tienes acceso a tu correo, el administrador puede asignarte una contraseña temporal.

### Elegir fundo y módulo **[Disponible]**

En la cabecera está el selector **Fundo › Módulo**. El sistema recuerda lo que elijas en tu
navegador y lo pone en la dirección de la página, así que puedes compartir el enlace. Al lado se
ve la fecha de hoy en Lima (en celular, dentro de **Menú**). Por ahora hay un solo fundo
(ENSUEÑO 1) y un solo módulo (EN01-MOD5). Desde la fase 2, cada pantalla muestra los datos del
módulo elegido.

---

## El flujo diario completo

Así funcionará el día a día cuando estén todas las fases. Cada paso indica quién lo hace y en qué
fase llega. **En la fase 1 todavía no hay cronogramas ni datos de riego**: solo están disponibles
el acceso, las contraseñas, los usuarios y la auditoría.

```text
05:00 ingesta ─► Generar ─► Revisar y corregir ─► Publicar ─► Visto del programador ─► Riego aplicado
 (sistema)      (encargado)    (encargado)        (encargado)     (programador)         (encargado / subgerente)
                                                       ▲                │
                                                       └── Solicitud de corrección (subgerente)
```

### Estados de un cronograma [Fase 3–4]

Hay un cronograma por módulo y fecha. Cada cambio guarda una versión nueva y las anteriores no se
borran nunca. El cronograma pasa por estos estados:

| Estado | Qué significa | Quién lo ve |
|---|---|---|
| **Borrador** | Lo generó el modelo o lo está corrigiendo el encargado. | Administrador, encargado, subgerente |
| **Publicado** | El encargado lo publicó; falta el Visto del programador. Si se modificó después de publicarse, aparece la etiqueta «Modificado · pendiente de visto». | Todos |
| **Visto** | El programador confirmó que lo recibió y lo programó. | Todos |
| **Corrección solicitada** | El subgerente pidió una corrección, con su motivo. | Todos (el programador ve la versión publicada con un aviso) |

Además, un cronograma puede llevar estas marcas de calidad:
- **Preliminar**: se calculó sin conocer todavía el riego real del día anterior (por ejemplo, los
  días 2 y 3 de una generación).
- **Datos incompletos**: faltaba alguna fuente de datos al generarlo.
- **Regenerado**: se volvió a calcular con el modelo.
- **Desactualizado**: llegaron datos nuevos después de generarlo; aparece con el botón
  **Regenerar**.

### Paso 1 · Llegan los datos de campo (automático) [Fase 2]

- **Quién**: el sistema.
- Cada día a las 05:00 descarga el clima de WeatherLink y los sensores de suelo y planta de Phytech
  hasta el día anterior.
- El panel de **frescura** muestra, por fuente, hasta qué fecha hay datos completos: verde si
  llegan hasta ayer, naranja si falta algo.
- El administrador y el encargado pueden tocar **Actualizar ahora** para repetir la descarga.

### Paso 2 · Cargar el riego aplicado desde Excel [Fase 2]

- **Quién**: encargado o administrador.
- **Riego aplicado → Subir Excel**: se sube el archivo del módulo (hoja `MOD5`) y el sistema
  muestra una **vista previa** por turno y día:
  - nuevo;
  - igual (no cambia nada);
  - reemplaza un provisional o un aplicado;
  - sin riego;
  - con error.
- Puedes desmarcar lo que no quieras aplicar y luego **Confirmar**. Subir otra vez el archivo
  acumulado completo no duplica nada.
- Si en una fecha del archivo falta un turno, la vista previa lo muestra como «no se regó», y
  puedes desmarcarlo.

### Paso 3 · Generar el cronograma [Fase 3]

- **Quién**: encargado o administrador.
- En **Generar**, elige la fecha inicial (por defecto, hoy) y el número de días (por defecto, 3),
  y revisa la frescura de cada día.
- El modelo propone, por turno, el número de ciclos y, por ciclo, los m³/ha, la duración y el
  horario, con un rango de confianza.
- El resultado dice qué pasó con cada día: creado, regenerado u omitido. Un día ya publicado o
  ya corregido no se toca, salvo que marques «regenerar también estos».

### Paso 4 · Revisar y corregir [Fase 3 lectura · Fase 4 edición]

- **Quién**: encargado o administrador. El subgerente lo ve en modo lectura.
- En **Cronogramas → detalle** hay cinco pestañas:
  - **Plan**: la tabla con los rangos;
  - **Gantt**;
  - **Datos**: clima, suelo y planta de los días previos;
  - **Versiones**: para comparar versiones;
  - **Línea de tiempo**.
- Al corregir puedes cambiar, por ciclo, los m³/ha, la duración y la hora de inicio, y por turno
  el número de ciclos.
  - La duración, los m³ y la hora de fin se recalculan solos.
  - Si un ciclo se solapa con el anterior, el sistema avisa, y **Ajustar solapes** lo corrige.
- Cada vez que guardas se crea una versión nueva. Si cambiaste algo respecto de la propuesta, se
  pide un **motivo**: clima o lluvia, criterio agronómico, programa semanal, falla de equipo,
  operación o personal, u otro.

### Paso 5 · Publicar [Fase 4]

- **Quién**: encargado o administrador.
- **Publicar** deja el cronograma en **Publicado** y envía un correo a los programadores y
  subgerentes con el botón «Ver cronograma».
- Si después hay que cambiar algo, se trabaja en un **borrador de cambios** que el programador no
  ve. Al tocar **Publicar cambios**, todos reciben el aviso con el resumen de lo que cambió.

### Paso 6 · Visto del programador [Fase 4]

- **Quién**: programador (o administrador).
- El programador abre el cronograma publicado, lo programa en el controlador y toca **Visto**.
- El subgerente recibe un correo, y el sistema crea el **riego provisional** de ese día a partir
  de lo visto.
- Si el cronograma se modificó después de su Visto, el programador ve las celdas que cambiaron
  resaltadas y debe confirmar de nuevo.
- En días pasados ya no se ofrece Visto.

### Paso 7 · Revisión del subgerente [Fase 4]

- **Quién**: subgerente (o administrador).
- Revisa el cronograma publicado o visto. Si algo no cuadra, toca **Solicitar corrección** y
  escribe el motivo; el encargado recibe un correo.
- El encargado atiende la solicitud de una de dos formas:
  - corrige y **Publicar cambios**, y el programador tendrá que volver a confirmar el Visto;
  - **Mantener versión publicada**, con un comentario obligatorio; el subgerente recibe el aviso.

### Paso 8 · Registrar lo que se regó [Fase 2 lectura · Fase 4 edición]

- **Quién**: encargado o subgerente (o administrador).
- En **Riego aplicado** se ve, por día y turno, el riego provisional (el que salió del Visto) y
  el aplicado (el real).
- Puedes editar el provisional y marcarlo como **aplicado**; solo se hace con días ya
  terminados.
- Si un turno no regó, registra **No se regó** con su motivo.
- Cada cambio guarda una versión nueva, y el historial conserva el original. El Excel del paso 2
  también deja el riego como aplicado.
- Lo aplicado alimenta al modelo para los días siguientes.

### Paso 9 · Seguimiento [Fase 5]

- **Quién**: todos, según su rol.
- El **Dashboard** muestra:
  - indicadores: agua aplicada ayer, aplicado frente al modelo, MDS (contracción del tronco),
    ETo de ayer y estado de mañana;
  - la frescura de los datos;
  - los cronogramas de hoy y mañana;
  - el pronóstico.
- **Datos de campo** muestra 14 días de agua aplicada frente a la propuesta por turno, MDS,
  crecimiento del tronco, humedad del suelo por profundidad y clima.
- Los cronogramas se exportan a PDF y Excel.
- El programador siempre ve la versión publicada, nunca la propuesta del modelo ni los borradores.

---

## Qué hace cada rol

### Administrador

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Crear, editar, activar y desactivar usuarios; asignar contraseñas temporales ([ver Usuarios](#usuarios-solo-administrador)) | **[Disponible]** |
| Revisar la auditoría ([ver Auditoría](#auditoría-administrador-y-subgerente)) | **[Disponible]** |
| Todo lo del encargado (generar, corregir, publicar, subir Excel, Actualizar ahora) | [Fases 2–4] |
| Confirmar Visto o solicitar corrección en lugar del programador o del subgerente | [Fase 4] |
| Exportar el CSV de refinamiento del modelo | [Fase 5] |

El primer administrador lo crea el equipo técnico al instalar el sistema (comando `crear-admin`).

### Encargado

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Ver el Dashboard (por ahora, con tarjetas vacías) | **[Disponible]** |
| Ver el riego aplicado, subir el Excel, revisar la frescura y usar **Actualizar ahora** (pasos 1 y 2) | [Fase 2] |
| Generar y regenerar cronogramas; ver el detalle (paso 3) | [Fase 3] |
| Corregir con motivo, publicar, publicar cambios, descartar el borrador de cambios y mantener la versión ante una solicitud de corrección (pasos 4, 5 y 7) | [Fase 4] |
| Editar el riego provisional, marcarlo aplicado y registrar «no se regó» (paso 8) | [Fase 4] |
| Dashboard con indicadores, Datos de campo y exportaciones (paso 9) | [Fase 5] |

### Programador

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Ver el Dashboard (por ahora, con tarjetas vacías) | **[Disponible]** |
| Consultar el riego aplicado | [Fase 2] |
| Ver los cronogramas publicados (nunca borradores ni la propuesta del modelo) | [Fase 3–4] |
| Recibir el correo de publicación, confirmar **Visto** y ver qué cambió desde su último Visto (paso 6) | [Fase 4] |
| Dashboard, Datos de campo y exportar la versión publicada (paso 9) | [Fase 5] |

### Subgerente

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Revisar la auditoría ([ver Auditoría](#auditoría-administrador-y-subgerente)) | **[Disponible]** |
| Ver el Dashboard (por ahora, con tarjetas vacías) | **[Disponible]** |
| Consultar el riego aplicado y la frescura | [Fase 2] |
| Ver los cronogramas (incluidos los borradores) en modo lectura | [Fase 3] |
| Recibir los correos de publicación y de Visto; **Solicitar corrección** con motivo (paso 7) | [Fase 4] |
| Editar el riego provisional, marcarlo aplicado y registrar «no se regó» (paso 8) | [Fase 4] |
| Dashboard con indicadores, Datos de campo y exportaciones (paso 9) | [Fase 5] |

---

## Usuarios (solo administrador)

**[Disponible]** Menú **Usuarios**. La tabla muestra nombre, usuario, correo, rol, estado y último
acceso. Puedes buscar por nombre, usuario o correo y filtrar por rol y por estado (activos o
inactivos).

### Crear un usuario

1. Toca **Nuevo usuario**.
2. Completa nombre completo, usuario, rol y correo.
   - El usuario admite letras sin tilde, números, punto, guion y guion bajo, de 3 a 60
     caracteres, y se guarda en minúsculas.
   - El correo recibe el enlace para recuperar la contraseña y, desde la fase 4, los avisos de
     los cronogramas.
3. Escribe una **contraseña temporal** o toca **Generar una segura**, y compártela con la persona
   por un medio seguro.
4. Toca **Crear usuario**. La persona deberá cambiar la contraseña temporal en su primer ingreso.
   Hasta que lo haga, en la tabla verás la etiqueta «Contraseña temporal».

### Otras acciones (menú ⋮ de la fila)

- **Editar**: cambia el nombre, el correo o el rol; el usuario no se puede cambiar. **Cambiar el
  rol cierra las sesiones de esa persona**, que deberá volver a ingresar.
- **Desactivar**: sus sesiones se cierran al instante y ya no puede ingresar ni recuperar la
  contraseña. Su historial se conserva.
- **Activar**: vuelve a ingresar con su contraseña de siempre.
- **Asignar contraseña temporal**: para quien olvidó su contraseña y no puede usar el correo. Sus
  sesiones se cierran y deberá cambiarla al ingresar. En tu propia fila, el menú ofrece **Cambiar
  mi contraseña** en su lugar.

### Reglas que el sistema hace cumplir

- No puedes desactivarte a ti mismo.
- Siempre debe quedar al menos un administrador activo.
- Si cambias tu propio rol, pierdes el acceso a esta pantalla y tendrás que volver a ingresar.
- Cambiar el correo, el rol, la contraseña o desactivar a alguien invalida los enlaces de
  recuperación que tuviera pendientes.

---

## Auditoría (administrador y subgerente)

**[Disponible]** Menú **Auditoría**. Es un registro de solo lectura de quién hizo qué y cuándo:
nadie puede editarlo ni borrarlo.

1. Filtra por **Usuario**, **Acción**, **Entidad** y rango de fechas (**Desde** / **Hasta**, días
   completos en hora de Lima).
2. La tabla está paginada; usa los botones de abajo para avanzar.
3. Toca una fila para abrir el **detalle**. Ahí verás:
   - la fecha y hora;
   - quién lo hizo y con qué rol;
   - desde qué dirección IP y qué navegador;
   - los datos de la acción. En las ediciones, una tabla **antes / después** resalta los valores
     que cambiaron.

En la fase 1 se registran:
- **Sesión**: inicio y cierre de sesión, e intentos de ingreso fallidos con su motivo.
- **Contraseñas**: recuperación solicitada, contraseña restablecida o cambiada, e intentos de
  cambio fallidos.
- **Usuarios**: alta, edición, cambio de rol, activación, desactivación y contraseña temporal
  asignada.

Nunca se guardan contraseñas ni enlaces de recuperación. Si alguien escribe en el campo usuario un
nombre que no existe, el intento se registra sin ese texto, porque podría ser una contraseña
escrita por error.

Desde las fases 2 a 5 también se registrarán las acciones sobre cronogramas, riego, cargas de Excel,
ingestas manuales y exportaciones.

---

## Qué trae cada fase

| Fase | Qué se agrega | Quién lo usa |
|---|---|---|
| **1 · Base** (disponible) | Ingresar, primer ingreso, recuperar y cambiar contraseña, selector de fundo y módulo, **Usuarios** y **Auditoría**. | Todos; Usuarios solo el administrador; Auditoría el administrador y el subgerente |
| 2 · Datos | **Riego aplicado**: consulta por turno y día y carga del Excel con vista previa. Ingesta diaria de WeatherLink y Phytech y panel de frescura con «Actualizar ahora». | El encargado sube el Excel; todos consultan |
| 3 · Predicción | **Generar** cronogramas de uno o más días; listado y detalle de **Cronogramas** en lectura; regenerar. | El encargado y el administrador generan; todos según su visibilidad |
| 4 · Flujo | Corrección con motivo, publicación, borrador de cambios, «Visto» del programador, solicitud de corrección, mantener versión, riego provisional y aplicado, línea de tiempo y correos de aviso. | Todos según su rol |
| 5 · Gráficos | **Dashboard** con indicadores, **Datos de campo** (clima, suelo y planta) y exportación a PDF y Excel. | Todos (el programador, sin la propuesta del modelo) |
| 6 · Pulido | Instalar el sistema en el celular como aplicación, ajustes finos en pantallas pequeñas, accesibilidad y la versión final de esta guía. | Todos |

Esta guía se ampliará con cada fase.

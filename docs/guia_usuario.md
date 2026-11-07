# Guía de usuario · Sistema de Plan de Riego

Grupo El Rocío (AvoPeru y Talsa) · fundo ENSUEÑO 1 · módulo EN01-MOD5

Esta guía explica cómo usar el sistema según tu rol. Describe lo que ya está disponible (fase 1:
acceso, contraseñas, usuarios y auditoría). Las pantallas de las próximas fases aparecen en el menú
con el aviso «Disponible en la fase N» y se documentarán cuando lleguen.

Todas las fechas y horas del sistema están en **hora de Lima**.

## Roles

| Rol | Qué hace en el sistema |
|---|---|
| **Administrador** | Gestiona los usuarios y revisa la auditoría. Ve todas las pantallas. |
| **Encargado** | Genera, corrige y publica los cronogramas de riego, y edita el riego aplicado (próximas fases). |
| **Subgerente** | Revisa los cronogramas y solicita correcciones (próximas fases). Revisa la auditoría. |
| **Programador** | Ve los cronogramas publicados y confirma el «Visto» en campo (próximas fases). |

Pantallas del menú por rol:

| Pantalla | Administrador | Encargado | Subgerente | Programador | Disponible |
|---|---|---|---|---|---|
| Dashboard | ✔ | ✔ | ✔ | ✔ (solo lo publicado) | Fase 1: tarjetas vacías hasta las fases 2–5 |
| Generar | ✔ | ✔ | — | — | Fase 3 |
| Cronogramas | ✔ | ✔ | ✔ | ✔ | Fases 3 y 4 |
| Riego aplicado | ✔ | ✔ | ✔ | ✔ | Fase 2 |
| Datos de campo | ✔ | ✔ | ✔ | ✔ | Fase 5 |
| Auditoría | ✔ | — | ✔ | — | **Fase 1** |
| Usuarios | ✔ | — | — | — | **Fase 1** |

Si entras a una pantalla que tu rol no puede ver, el sistema muestra «No tienes acceso a esta
sección». Si crees que es un error, pide al administrador que revise tu rol.

---

## Para todos los roles

### Ingresar

1. Abre la dirección del sistema que te dio el administrador.
2. Escribe tu **usuario** y tu **contraseña** y toca **Ingresar**.
3. Si abriste un enlace a una pantalla concreta, después de ingresar vuelves a esa pantalla.

- Si el usuario o la contraseña no son correctos, verás «Usuario o contraseña incorrectos» (el
  mensaje es el mismo en los dos casos, por seguridad).
- Después de varios intentos fallidos el ingreso se bloquea unos minutos: «Demasiados intentos.
  Vuelve a intentarlo en N minutos.»
- La sesión se mantiene en ese navegador: si pasas 7 días sin usar el sistema (o 30 días desde
  que ingresaste), tendrás que volver a ingresar. Para salir, abre el menú con
  tu nombre (arriba a la derecha; en celular, **Menú** abajo) y elige **Cerrar sesión**. Cerrar
  sesión en una pestaña la cierra en todas las pestañas de ese navegador.
- Si el servidor no responde al abrir el sistema, verás «No se pudo conectar» con el botón
  **Reintentar**. Tu sesión no se pierde: reintenta cuando vuelva la conexión.

### Primer ingreso: crear tu contraseña

El administrador te da de alta con una **contraseña temporal**. La primera vez que ingreses, el
sistema te lleva a **Crea tu contraseña** y no deja usar nada más hasta que la cambies:

1. En **Contraseña temporal**, escribe la que te dio el administrador.
2. Escribe tu **Nueva contraseña** y repítela.
3. Toca **Guardar contraseña**. Entrarás al sistema con la contraseña nueva.

La contraseña debe tener **al menos 10 caracteres, con letras y números**, y no puede ser igual a tu
usuario. La lista bajo el campo marca cada requisito a medida que lo cumples.

### Cambiar tu contraseña

Abre el menú con tu nombre y elige **Cambiar contraseña**. Escribe la actual y la nueva dos veces.
Al guardar, se cierran tus sesiones en otros dispositivos; en el que estás sigues dentro.

### Olvidé mi contraseña

1. En la pantalla de ingreso, toca **¿Olvidaste tu contraseña?**
2. Escribe tu usuario o tu correo y toca **Enviar enlace**.
3. Revisa tu correo (también la carpeta de correo no deseado) y toca **Restablecer contraseña**.
   El enlace es de **un solo uso** y vence en poco tiempo (30 minutos con la configuración
   por defecto).
4. Escribe la nueva contraseña dos veces y toca **Guardar contraseña**. Se cierran todas tus
   sesiones abiertas; ingresa de nuevo con la contraseña nueva.

- El sistema siempre responde «Si el usuario existe, enviaremos un enlace a su correo», exista o no
  el usuario, para no revelar quién tiene cuenta.
- Si el enlace venció o ya se usó, verás «El enlace no es válido o ya venció» y podrás pedir uno nuevo.
- Si tu usuario está desactivado no llegará el correo: habla con el administrador.

### Elegir fundo y módulo

En la cabecera está el selector **Fundo › Módulo**. Lo que elijas se recuerda en tu navegador y
aparece en la dirección de la página, así que puedes compartir el enlace. Al lado se ve la fecha de
hoy en Lima (en celular, dentro de **Menú**).

---

## Administrador

### Gestionar usuarios

Menú **Usuarios**. La tabla muestra nombre, usuario, correo, rol, estado y último acceso. Puedes
buscar por nombre, usuario o correo y filtrar por rol y por estado (activos o inactivos).

**Crear un usuario**

1. Toca **Nuevo usuario**.
2. Completa nombre completo, usuario, rol y correo. El usuario admite letras sin tilde, números,
   punto, guion y guion bajo (de 3 a 60 caracteres) y se guarda en minúsculas. El correo recibe el
   enlace para recuperar la contraseña.
3. Escribe una **contraseña temporal** o toca **Generar una segura**, y compártela con la persona
   por un medio seguro.
4. Toca **Crear usuario**. La persona deberá cambiar la contraseña temporal en su primer ingreso
   (en la tabla verás la etiqueta «Contraseña temporal» hasta que lo haga).

**Editar** (menú ⋮ de la fila → **Editar**): cambia nombre, correo o rol. El usuario no se puede
cambiar. **Cambiar el rol cierra las sesiones de esa persona**, que deberá volver a ingresar.

**Desactivar o activar** (menú ⋮ → **Desactivar** / **Activar**): al desactivar, sus sesiones se
cierran al instante y no puede ingresar ni recuperar la contraseña; su historial se conserva. Al
activar, vuelve a ingresar con su contraseña de siempre.

**Asignar contraseña temporal** (menú ⋮): para quien olvidó su contraseña y no puede usar el correo.
Sus sesiones se cierran y deberá cambiarla al ingresar. Para tu propia cuenta, el menú ofrece
**Cambiar mi contraseña** en su lugar.

Reglas que el sistema hace cumplir:

- No puedes desactivarte a ti mismo.
- Siempre debe quedar al menos un administrador activo.
- Si cambias tu propio rol, pierdes el acceso a esta pantalla y tendrás que volver a ingresar.

El primer administrador lo crea el equipo técnico al instalar el sistema (comando `crear-admin`).

---

## Administrador y subgerente

### Revisar la auditoría

Menú **Auditoría**. Es un registro de solo lectura (nadie puede editarlo ni borrarlo) de quién hizo
qué y cuándo.

1. Filtra por **Usuario**, **Acción**, **Entidad** y rango de fechas (**Desde** / **Hasta**, días
   completos en hora de Lima).
2. La tabla está paginada; usa los botones de abajo para avanzar.
3. Toca una fila para abrir el **detalle**: fecha y hora, quién lo hizo y con qué rol, desde qué
   dirección IP y navegador, y los datos de la acción. En las ediciones verás una tabla **antes /
   después** con los valores que cambiaron resaltados.

En la fase 1 se registran: inicio y cierre de sesión, intentos de ingreso fallidos (con el motivo),
recuperación solicitada, contraseña restablecida, cambiada o con intento de cambio fallido, y en
usuarios: alta, edición, cambio de rol, activación, desactivación y contraseña temporal asignada.
Nunca se guardan contraseñas ni enlaces de recuperación.

---

## Próximas fases

| Fase | Qué se agrega | Quién lo usa |
|---|---|---|
| 2 · Datos | **Riego aplicado**: consulta por turno y día, carga del Excel con vista previa. Frescura de los datos de riego, WeatherLink y Phytech, con «Actualizar ahora». | Encargado y subgerente editan; todos consultan |
| 3 · Modelo | **Generar** cronogramas de uno o más días; listado y detalle de **Cronogramas**. | Encargado y administrador generan |
| 4 · Flujo | Corrección con motivo, publicación, «Visto» del programador, solicitud de corrección del subgerente y notificaciones por correo. | Todos según su rol |
| 5 · Gráficos | **Dashboard** con indicadores, **Datos de campo** (clima, suelo y planta) y exportación a PDF y Excel. | Todos (el programador sin la propuesta del modelo) |

Esta guía se ampliará con cada fase.

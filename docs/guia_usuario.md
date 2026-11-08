# Guía de usuario · Sistema de Plan de Riego

Grupo El Rocío (AvoPeru y Talsa) · fundo ENSUEÑO 1 · módulo EN01-MOD5

Esta guía explica cómo usar el sistema según tu rol. Cada función lleva una marca:

- **[Disponible]**: ya se puede usar (fases 1 a 4).
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
| Dashboard | ✔ | ✔ | ✔ (solo lo publicado) | ✔ | **[Disponible]** frescura, Hoy y mañana y Estado de mañana; otros indicadores y pronóstico en fase 5 |
| Generar | ✔ | ✔ | — | — | [Disponible] |
| Cronogramas | ✔ | ✔ edita | ✔ solo publicados, confirma Visto | ✔ lectura, solicita corrección | **[Disponible]** |
| Riego aplicado | ✔ | ✔ sube Excel y edita | ✔ lectura | ✔ lectura, historial y edición | **[Disponible]** consulta, Excel y edición |
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
(ENSUEÑO 1) y un solo módulo (EN01-MOD5). **Riego aplicado**, la carga de Excel y la **Frescura de
datos** del Dashboard muestran los datos del módulo elegido.

---

## El flujo diario completo

Ya están disponibles los pasos 1 a 8: llegada de datos, carga de Excel, generación, revisión,
publicación, Visto, solicitud de corrección y registro del riego. El seguimiento con gráficos
y exportaciones se completa en la fase 5.

```text
05:00 ingesta ─► Generar ─► Revisar y corregir ─► Publicar ─► Visto del programador ─► Riego aplicado
 (sistema)      (encargado)    (encargado)        (encargado)     (programador)         (encargado / subgerente)
                                                       ▲                │
                                                       └── Solicitud de corrección (subgerente)
```

### Estados de un cronograma [Disponible]

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

### Paso 1 · Llegan los datos de campo (automático) **[Disponible]**

- **Quién**: el sistema. Cada día a las 05:00 descarga el clima de WeatherLink, los sensores de
  suelo y planta de Phytech, las imágenes NDVI y el pronóstico, hasta el día anterior. Los datos de
  WeatherLink se guardan en las mismas unidades con las que se entrenó el modelo (°C, mm y km).
- En el **Dashboard**, la tarjeta **Frescura de datos** muestra, por fuente (Riego aplicado, Riego
  provisional, WeatherLink (clima), Phytech suelo, Phytech planta, NDVI y Pronóstico Phytech):
  - «Hasta <día>»: la última fecha con datos completos;
  - **Al día** (verde) si llega hasta ayer, o **Atrasado** (naranja) con «faltan N días»;
  - «Huecos: …» si en los últimos 7 días falta algún día intermedio;
  - en el riego, una línea solo para los turnos que están distintos al resto, por ejemplo
    «TE05: falta mar 03/11» o «TE03: hasta mié 04/11»;
  - NDVI y Pronóstico Phytech son **Informativo**: no ponen el panel en naranja (las imágenes
    satelitales llegan cada pocos días).
  Arriba se resume todo: «Todo al día» o, por ejemplo, «2 fuentes atrasadas · 1 con huecos».
- **Actualizar ahora** (administrador y encargado): repite la descarga en segundo plano. El botón
  pasa a «Actualizando…» y una barra muestra «Actualizando: N de M fuentes terminadas». Al terminar
  verás «Datos actualizados», «Actualización parcial» o «La actualización falló», y la frescura se
  vuelve a calcular. Si ya hay una descarga en curso (la de las 05:00 u otra persona), el botón
  espera a que termine.
- **Últimas corridas** (administrador, encargado y subgerente): cada descarga por fuente, con su
  estado (**En curso**, **Correcta**, **Parcial** o **Error**), la hora, quién la lanzó
  (Programada, Manual · usuario o Script), cuánto duró, el rango de días, las filas nuevas y
  actualizadas y, si falló, el motivo. Una descarga que quedó **Sin terminar** (el servidor se
  reinició a mitad) no bloquea nada: se cierra sola al usar **Actualizar ahora**.

### Paso 2 · Cargar el riego aplicado desde Excel **[Disponible]**

- **Quién**: encargado o administrador.
1. En **Riego aplicado** toca **Cargar Excel**.
2. «Arrastra el archivo aquí o toca para elegirlo»: el Excel del controlador (`.xlsx` de hasta
   15 MB, con la hoja `MOD5`). Puede ser el archivo acumulado completo. Toca **Subir y revisar**.
   Si el archivo no sirve (no es `.xlsx`, falta la hoja o una columna, trae fechas de hoy o
   futuras…) verás «No se pudo procesar el archivo» con el motivo.
3. **Vista previa de la carga**: nada se guarda todavía. Arriba, una tarjeta por resultado con
   cuántos turno-días hay:
   - **Nuevo**: turno-día sin registro; se crea como aplicado.
   - **Igual**: igual a lo que ya está; no crea versión.
   - **Reemplaza provisional**: cambia el riego provisional por el aplicado del Excel.
   - **Reemplaza aplicado**: cambia un riego ya aplicado (si el actual se cargó a mano, viene
     desmarcado).
   - **Sin riego**: el archivo trae la fecha pero ninguna fila de ese turno; se registra «no se
     regó». Viene marcado y puedes desmarcarlo.
   - **Error**: no se puede cargar (fecha de hoy o futura, turno o válvula desconocidos, inicio
     repetido).
   Cada tarjeta tiene la casilla **Aplicar todos** y tocar la tarjeta filtra el detalle. Abajo,
   **Detalle por turno-día** («Con cambios» o «Todos») con fecha, turno, resultado, ciclos, el
   registro que se reemplaza y su casilla.
4. La barra de abajo dice «Se aplicarán N turno-días». Toca **Confirmar** y, en «¿Confirmar la
   carga?», **Confirmar carga**. Verás «Carga confirmada: N turno-días aplicados» y **Ver riego
   aplicado**. Lo reemplazado no se borra: queda como versión anterior.
5. Si no quieres guardar nada, **Descartar** → «¿Descartar la carga?» → **Descartar**.

- Algunos turno-días llegan **desmarcados con un aviso** en el detalle, para que los revises antes
  de aplicarlos: los de la **última fecha del archivo** que reemplazan un aplicado o quedan «sin
  riego» («puede venir incompleta (exportado a mitad del día)») y los que traen **menos riego que
  lo ya aplicado**. Márcalos solo si comprobaste que el dato del Excel es el correcto.
- Subir otra vez el archivo acumulado completo no duplica nada: lo ya cargado sale como «Igual».
- **La carga venció**: la vista previa dura 24 horas y vence también si alguien cambia uno de los
  registros comparados. Toca **Subir otra vez** para revisarla con los datos actuales.
- La subida, la confirmación y el descarte quedan en la **Auditoría**.

### Paso 3 · Generar el cronograma [Disponible]

- **Quién**: encargado o administrador.
- En **Generar**, elige la **Fecha inicial** (por defecto, hoy; puede ir de 7 días atrás hasta
  mañana) y los **Días** (por defecto, 3; máximo 7) y toca **Generar**. El modelo tarda unos
  segundos por día.
- El modelo propone, por turno, el número de ciclos y, por ciclo, los m³/ha, la duración y el
  horario.
- **Resultado por día**: dice qué pasó con cada día (**Creado**, **Regenerado** u **Omitido**),
  su versión y sus marcas, con **Ver detalle**. Si alguna fuente no tenía el día anterior aparece
  «Datos atrasados al generar»: el plan se calcula igual, con menos precisión.
- Un día ya publicado o ya corregido no se toca, salvo que marques «Regenerar también los días con
  correcciones o publicados»: se crea una versión nueva del modelo como borrador y lo publicado no
  cambia hasta que se publique.
- Si alguien está generando el mismo módulo en ese momento, el sistema avisa y pide intentar de
  nuevo en unos segundos.

### Ver un cronograma [Disponible]

- En **Cronogramas** están los cronogramas por fecha (por defecto, del último mes a la próxima
  semana), con su estado, versión y marcas. El programador solo ve los publicados.
- El **detalle** abre **Plan**, con inicio, fin, duración, m³/ha y m³ de cada ciclo; la luna
  indica que termina al día siguiente. **Gantt** muestra los horarios a ancho completo.
  En la pestaña **Versiones**, toca una para verla en Plan.
- Filtra el listado con **Todos**, **Borrador** (incluye cambios sin publicar), **Publicado**,
  **Visto**, **Corrección solicitada** y **Modificado**.
- **Regenerar** (encargado y administrador) recalcula el día con el modelo y crea una versión
  nueva. Si el borrador tenía correcciones, el sistema pide confirmar («Regenerar igual»).
- Si llegaron datos nuevos después de generar, aparece la marca **Desactualizado** y el aviso
  «Hay datos nuevos»: conviene regenerar.
- En el **Dashboard**, **Hoy y mañana** muestra el Gantt de los dos días con su estado y versión.
  **Estado de mañana** muestra Borrador, Publicado, Visto, Corrección solicitada o «Sin cronograma».

### Paso 4 · Revisar y corregir [Disponible]

- **Quién**: encargado o administrador. El subgerente consulta sin editar el plan.
- El detalle tiene **Plan**, **Gantt**, **Datos**, **Versiones** y **Línea de tiempo**. El
  programador solo ve Plan y Gantt. Puedes recorrer las pestañas con las flechas del teclado.
- En **Plan**, toca **Corregir**. Se abre el borrador vigente o la versión publicada; al guardar
  sobre una publicada se crea un borrador de cambios que el programador todavía no ve.
- Por ciclo, edita **m³/ha**, **Inicio** y **Día siguiente**. La duración, el volumen y el fin se
  recalculan. Marca **Duración manual** para fijar los minutos; es obligatorio si falta el factor
  del turno. **N.º de ciclos** reemplaza el turno por la alternativa del modelo de 1 a 5 ciclos.
- Las celdas modificadas se ven en verde. Los solapes avisan sin impedir guardar; **Ajustar
  solapes** retrasa los inicios que se superponen hasta el fin del ciclo anterior.
- **Cancelar** sale directamente si no cambiaste nada. Si hay cambios, confirma con **Descartar
  corrección** o usa **Volver** para continuar editando.
- **Guardar corrección** abre el diálogo: elige **Motivo**, añade **Comentario (opcional)** y
  toca **Guardar corrección**. Verás «Se guardó la versión vN».
- Si alguien cambió el cronograma, aparece «Otro usuario modificó el cronograma. Recarga para
  ver los cambios.». **Recargar** abandona la edición y trae el detalle actual.
- **Datos** muestra los siete días previos con ETo, temperatura, HR, lluvia, humedad de suelo y
  MDS; las columnas sin datos se omiten. **Versiones** permite elegir **Comparar** vN **Con** vM
  y muestra turno, ciclo, campo y antes → después; inicia con publicada contra borrador.
- **Línea de tiempo** muestra las acciones desde la más reciente, con fecha y hora de Lima,
  usuario, versión y motivo o comentario. Las aperturas del programador y del subgerente también
  quedan registradas; abrir el detalle no equivale a confirmar Visto.

### Paso 5 · Publicar [Disponible]

- **Quién**: encargado o administrador.
- **Publicar** pide confirmar «Se avisará al programador y al subgerente». Los avisos de correo
  quedan en cola para su envío.
- Tras corregir una publicada, usa **Publicar cambios**: «El programador deberá confirmar el
  Visto de nuevo». Para días pasados: «Corrección retrospectiva: solo se avisa al subgerente».
- **Descartar cambios** elimina el borrador abierto y conserva la publicada y el historial.
- El chip **Modificado · pendiente de visto** identifica un cronograma publicado más de una vez.
  Si el servidor devuelve avisos sobre la sincronización del riego, aparecen bajo las acciones.

### Paso 6 · Visto del programador [Disponible]

- **Quién**: programador o administrador, en cronogramas publicados de hoy o futuros.
- Revisa la versión publicada, prográmala en el controlador y toca **Confirmar Visto**; confirma
  también en el diálogo. Verás «Visto confirmado».
- El sistema avisa al subgerente y crea o actualiza el **riego provisional**. Conserva los
  registros aplicados y los provisionales editados manualmente; los avisos aparecen en pantalla.
- Si cambió la publicada mientras confirmabas, aparece «Hay una versión publicada más nueva» y
  se recarga el detalle. Revísala antes de confirmar otra vez.
- **Cambió desde tu Visto** muestra diferencias cuando el servidor conserva tu versión vista y
  ambas versiones son visibles. Al publicar cambios de hoy/futuros el servidor limpia ese dato;
  en ese caso aparece el chip de modificación y se ofrece confirmar Visto de nuevo.
- En días pasados no se ofrece Visto.

### Paso 7 · Revisión del subgerente [Disponible]

- **Quién**: subgerente o administrador. Sobre un cronograma **Publicado** o **Visto**, toca
  **Solicitar corrección**, escribe un **Motivo** de 5 a 1000 caracteres y confirma. El contador
  ayuda a respetar el límite. El encargado recibe el aviso.
- La cabecera muestra **Corrección solicitada**, el motivo, quién la pidió y cuándo.
- El encargado o administrador puede corregir y **Publicar cambios**, o usar **Mantener versión**
  con un **Comentario** de 5 a 1000 caracteres. El subgerente recibe el aviso de la decisión.

### Paso 8 · Registrar lo que se regó [Disponible]

- **Quién**: consultan todos; editan el administrador, el encargado y el subgerente.
- **Riego aplicado** muestra día y turno, estado (**Aplicado**, **Provisional**, **Sin riego**,
  **Sin registro**), m³/ha y horarios. Filtra con **Desde**, **Hasta**, **7 días**, **14 días** o
  **30 días** (máximo 92 días). En celular los días se muestran como tarjetas.
- Toca un turno-día con registro para ver los ciclos. A/E/S ven también el **Historial de
  versiones**, con **Original**, **Vigente**, origen, fecha, usuario y motivo.
- **Editar riego** habilita inicio HH:MM, **Día siguiente**, duración y m³/ha. **Agregar ciclo** y
  **Quitar** mantienen entre 1 y 5 ciclos. Completa **Motivo** (1–255 caracteres) y, si quieres,
  **Comentario (opcional)**; toca **Guardar riego**. Verás «Se guardó el riego».
- **No se regó** guarda el día sin ciclos y también exige motivo. Conserva el estado del vigente.
- **Marcar aplicado** solo aparece para un provisional de una fecha anterior a hoy. Conserva los
  mismos ciclos, pide motivo y confirma con **Marcar aplicado**. Verás «Riego marcado como aplicado».
- Si otro usuario cambió el vigente, aparece «Otro usuario cambió este riego. Recarga.».
  **Recargar** cierra la edición y obtiene el registro actual; luego puedes volver a editar.
- Cada guardado crea una versión manual. Las celdas **Sin registro** todavía no abren un editor;
  la creación de provisionales ocurre al confirmar Visto y la carga de Excel crea los aplicados.
- Lo aplicado alimenta al modelo para los días siguientes.

### Paso 9 · Seguimiento [Fase 5]

- **Quién**: todos, según su rol.
- El **Dashboard** muestra:
  - indicadores: agua aplicada ayer, aplicado frente al modelo, MDS (contracción del tronco),
    ETo de ayer (fase 5); **Estado de mañana** ya está disponible;
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
| Subir el Excel de riego, usar **Actualizar ahora**, ver las últimas corridas y el historial de versiones (pasos 1, 2 y 8) | **[Disponible]** |
| Todo lo demás del encargado (generar, corregir, publicar) | [Disponible] |
| Confirmar Visto o solicitar corrección en lugar del programador o del subgerente | [Disponible] |
| Exportar el CSV de refinamiento del modelo | [Fase 5] |

El primer administrador lo crea el equipo técnico al instalar el sistema (comando `crear-admin`).

### Encargado

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Ver el Dashboard con la **Frescura de datos** y las últimas corridas | **[Disponible]** |
| Ver el riego aplicado y su historial, subir el Excel y usar **Actualizar ahora** (pasos 1, 2 y 8) | **[Disponible]** |
| Generar y regenerar cronogramas; ver el detalle (paso 3) | [Disponible] |
| Corregir con motivo, publicar, publicar cambios, descartar el borrador de cambios y mantener la versión ante una solicitud de corrección (pasos 4, 5 y 7) | [Disponible] |
| Editar el riego provisional, marcarlo aplicado y registrar «no se regó» (paso 8) | [Disponible] |
| Dashboard con indicadores, Datos de campo y exportaciones (paso 9) | [Fase 5] |

### Programador

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Ver el Dashboard con la **Frescura de datos** (sin «Actualizar ahora» ni corridas) | **[Disponible]** |
| Consultar el riego aplicado por turno y día, con sus ciclos (paso 8) | **[Disponible]** |
| Ver los cronogramas publicados (nunca borradores ni la propuesta del modelo) | [Disponible] |
| Recibir el correo de publicación, confirmar **Visto** y ver qué cambió desde su último Visto (paso 6) | [Disponible] |
| Dashboard, Datos de campo y exportar la versión publicada (paso 9) | [Fase 5] |

### Subgerente

| Qué | Disponible |
|---|---|
| Ingresar, recuperar y cambiar su contraseña | **[Disponible]** |
| Revisar la auditoría ([ver Auditoría](#auditoría-administrador-y-subgerente)) | **[Disponible]** |
| Ver el Dashboard con la **Frescura de datos** y las últimas corridas (sin «Actualizar ahora») | **[Disponible]** |
| Consultar el riego aplicado y el historial de versiones de cada turno-día (paso 8) | **[Disponible]** |
| Ver los cronogramas (incluidos los borradores) en modo lectura | [Disponible] |
| Recibir los correos de publicación y de Visto; **Solicitar corrección** con motivo (paso 7) | [Disponible] |
| Editar el riego provisional, marcarlo aplicado y registrar «no se regó» (paso 8) | [Disponible] |
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
   - El correo recibe el enlace para recuperar la contraseña y los avisos de
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

Desde la fase 2 se registran también:
- **Cargas de Excel de riego**: «Excel de riego subido», «Excel de riego confirmado» y «Excel de
  riego descartado», con el archivo, los contadores y el rango de fechas.
- **Datos de campo**: «Lecturas del Excel histórico reemplazadas por WeatherLink» cuando el equipo
  técnico fuerza ese reemplazo.

Desde las fases 3 y 4 se registran las acciones sobre cronogramas y la edición del riego.
Las exportaciones se agregan en la fase 5.

---

## Qué trae cada fase

| Fase | Qué se agrega | Quién lo usa |
|---|---|---|
| **1 · Base** (disponible) | Ingresar, primer ingreso, recuperar y cambiar contraseña, selector de fundo y módulo, **Usuarios** y **Auditoría**. | Todos; Usuarios solo el administrador; Auditoría el administrador y el subgerente |
| **2 · Datos** (disponible) | **Riego aplicado**: consulta por turno y día, historial de versiones y carga del Excel con vista previa. Ingesta diaria de WeatherLink y Phytech y panel de **Frescura de datos** con «Actualizar ahora» y últimas corridas. | El encargado y el administrador suben el Excel y actualizan; todos consultan |
| **3 · Predicción** (disponible) | **Generar** cronogramas de uno o más días; listado y detalle de **Cronogramas** en lectura; regenerar. | El encargado y el administrador generan; todos según su visibilidad |
| **4 · Flujo** (disponible) | Corrección con motivo, publicación, borrador de cambios, «Visto» del programador, solicitud de corrección, mantener versión, riego provisional y aplicado, línea de tiempo y correos de aviso. | Todos según su rol |
| 5 · Gráficos | **Dashboard** con indicadores, **Datos de campo** (clima, suelo y planta) y exportación a PDF y Excel. | Todos (el programador, sin la propuesta del modelo) |
| 6 · Pulido | Instalar el sistema en el celular como aplicación, ajustes finos en pantallas pequeñas, accesibilidad y la versión final de esta guía. | Todos |

Esta guía se ampliará con cada fase.

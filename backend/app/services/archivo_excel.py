"""Validación de un Excel subido (§3.5 punto 1 y §7) antes de abrirlo con pandas/openpyxl.

Un ``.xlsx`` es un ZIP de XML: se defiende contra bombas de descompresión y contra XML con DTD o
entidades (*billion laughs*, XXE) **antes** de parsearlo. El contenido se lee con tope de tamaño
y se procesa desde memoria (``BytesIO``); la app nunca lo guarda en disco ni lo conserva después
de la vista previa (solo nombre saneado, sha256 y tamaño; el temporal de Starlette se borra al
cerrar el formulario):

1. Nombre ``.xlsx`` y tamaño ≤ ``UPLOAD_MAX_MB`` (15 MB).
2. Firma ZIP (``PK\\x03\\x04``) y ZIP legible, con a lo sumo :data:`MAX_MIEMBROS` partes.
3. Tamaño descomprimido declarado ≤ :data:`MAX_DESCOMPRIMIDO` (200 MB) y relación
   descomprimido/comprimido ≤ :data:`MAX_RELACION` (100). ``zipfile`` nunca entrega más bytes de
   los declarados (y verifica el CRC), así que el límite sobre lo declarado es real.
4. Cada parte XML se abre con ``defusedxml`` (sin DTD, sin entidades, sin referencias externas);
   una DTD solo puede ir antes del elemento raíz, así que basta leer hasta él.
5. Hoja pedida (``MOD5``) presente en ``xl/workbook.xml``.
6. openpyxl (lo usa ``pandas.read_excel``) debe estar usando ``defusedxml``; si no, se rechaza.
7. La hoja se recorre una vez en *streaming* (``defusedxml.iterparse``, sin pandas) antes de
   leerla: a lo sumo :data:`MAX_FILAS` filas de datos (se corta al pasarse, sin leer el resto) y
   ninguna celda con fórmula sin valor guardado (archivos generados por script u openpyxl y nunca
   abiertos en Excel: pandas las lee vacías y un turno regado parecería «no se regó»).

Las comprobaciones de columnas (las 10 de ``leer_riego``) se hacen al leer la hoja
(``carga_riego_service``).
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from app.core.config import settings
from app.core.errores import DatosInvalidos, ErrorApp

FIRMA_ZIP = b"PK\x03\x04"
MAX_DESCOMPRIMIDO = 200 * 1024 * 1024
MAX_RELACION = 100
MAX_MIEMBROS = 1000
MAX_FILAS = 100_000
EXTENSION = ".xlsx"
PARTES_OBLIGATORIAS = ("[Content_Types].xml", "xl/workbook.xml")
_NS_HOJA = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL_DOC = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_REL_PAQ = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_RELS_LIBRO = "xl/_rels/workbook.xml.rels"
MAX_EJEMPLOS_FORMULA = 5
_TROZO = 1024 * 1024
_NOMBRE_NO_PERMITIDO = re.compile(r"[^\w .,()\[\]-]+")


class ArchivoDemasiadoGrande(ErrorApp):
    status_code = 413


class ArchivoInvalido(DatosInvalidos):
    """El archivo no pasa la validación (422)."""


class CargaNoDisponible(ErrorApp):
    status_code = 503


@dataclass(frozen=True)
class ArchivoValidado:
    nombre: str  # saneado
    contenido: bytes
    sha256: str

    @property
    def tamano(self) -> int:
        return len(self.contenido)

    def abrir(self) -> io.BytesIO:
        return io.BytesIO(self.contenido)


def max_bytes() -> int:
    return settings.upload_max_mb * 1024 * 1024


def nombre_saneado(nombre: str | None) -> str:
    """Solo el nombre (sin carpetas), NFC, sin caracteres de control ni símbolos raros, ≤ 255."""
    base = (nombre or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(c for c in base if unicodedata.category(c)[0] != "C")
    base = _NOMBRE_NO_PERMITIDO.sub("_", base).strip(" .")
    base = re.sub(r"\s+", " ", base)
    if not base.lower().endswith(EXTENSION):
        base = (base or "archivo") + EXTENSION
    if len(base) > 255:
        base = base[: 255 - len(EXTENSION)] + EXTENSION
    return base


def leer_limitado(origen: BinaryIO, limite: int | None = None) -> bytes:
    """Lee a lo sumo ``limite`` bytes; si hay más, 413 (sin cargar el resto en memoria)."""
    limite = max_bytes() if limite is None else limite
    partes: list[bytes] = []
    total = 0
    while True:
        trozo = origen.read(_TROZO)
        if not trozo:
            break
        total += len(trozo)
        if total > limite:
            raise ArchivoDemasiadoGrande(
                f"El archivo supera el máximo de {settings.upload_max_mb} MB."
            )
        partes.append(trozo)
    return b"".join(partes)


def _verificar_openpyxl_seguro() -> None:
    from openpyxl.xml import DEFUSEDXML

    if not DEFUSEDXML:
        # Sin defusedxml openpyxl parsearía DTD y entidades: no se aceptan archivos.
        raise CargaNoDisponible("La carga de Excel no está disponible: falta defusedxml en el servidor.")


def _hojas(libro: bytes) -> list[str]:
    raiz = DefusedET.fromstring(libro, forbid_dtd=True)
    return [h.get("name", "") for h in raiz.iter(f"{_NS_HOJA}sheet")]


def _parte_de_hoja(archivo_zip: zipfile.ZipFile, hoja: str) -> str | None:
    """Ruta dentro del ZIP de la hoja ``hoja`` (``xl/worksheets/sheetN.xml``), por su relación."""
    libro = DefusedET.fromstring(archivo_zip.read("xl/workbook.xml"), forbid_dtd=True)
    rel_id = next((h.get(f"{_NS_REL_DOC}id") for h in libro.iter(f"{_NS_HOJA}sheet")
                   if h.get("name") == hoja), None)
    if rel_id is None or _RELS_LIBRO not in archivo_zip.namelist():
        return None
    relaciones = DefusedET.fromstring(archivo_zip.read(_RELS_LIBRO), forbid_dtd=True)
    destino = next((r.get("Target") for r in relaciones.iter(f"{_NS_REL_PAQ}Relationship")
                    if r.get("Id") == rel_id), None)
    if not destino:
        return None
    parte = destino.lstrip("/") if destino.startswith("/") else f"xl/{destino}"
    return parte if parte in archivo_zip.namelist() else None


@dataclass
class EscaneoHoja:
    filas: int = 0  # incluida la de encabezados
    formulas_sin_valor: int = 0
    ejemplos: list[str] | None = None
    cortado: bool = False  # se pasó de MAX_FILAS y no se leyó el resto


def escanear_hoja(archivo_zip: zipfile.ZipFile, parte: str, *, max_filas: int | None = None) -> EscaneoHoja:
    """Recorre la hoja en streaming: cuenta filas (corta al pasar ``max_filas`` de datos) y
    busca celdas con fórmula (``<f>``) sin valor guardado (``<v>`` vacío o ausente)."""
    max_filas = MAX_FILAS if max_filas is None else max_filas
    resultado = EscaneoHoja(ejemplos=[])
    fila, celda, formula, valor = f"{_NS_HOJA}row", f"{_NS_HOJA}c", f"{_NS_HOJA}f", f"{_NS_HOJA}v"
    with archivo_zip.open(parte) as flujo:
        for _evento, elemento in DefusedET.iterparse(
            flujo, events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True,
        ):
            if elemento.tag == fila:
                resultado.filas += 1
                elemento.clear()
                if resultado.filas > max_filas + 1:
                    resultado.cortado = True
                    break
            elif elemento.tag == celda and elemento.find(formula) is not None:
                guardado = elemento.find(valor)
                if guardado is None or not (guardado.text or "").strip():
                    resultado.formulas_sin_valor += 1
                    if len(resultado.ejemplos) < MAX_EJEMPLOS_FORMULA:
                        resultado.ejemplos.append(elemento.get("r") or "?")
    return resultado


def mensaje_max_filas(hoja: str) -> str:
    return f"La hoja {hoja} supera el máximo de {MAX_FILAS:,} filas.".replace(",", " ")


def _verificar_contenido_hoja(archivo_zip: zipfile.ZipFile, hoja: str) -> None:
    parte = _parte_de_hoja(archivo_zip, hoja)
    if parte is None:
        raise ArchivoInvalido(f"El archivo no es un Excel .xlsx válido (no se encuentra la hoja {hoja}).")
    escaneo = escanear_hoja(archivo_zip, parte)
    if escaneo.cortado:
        raise ArchivoInvalido(mensaje_max_filas(hoja))
    if escaneo.formulas_sin_valor:
        ejemplos = ", ".join(escaneo.ejemplos or [])
        raise ArchivoInvalido(
            f"La hoja {hoja} tiene {escaneo.formulas_sin_valor} celda(s) con fórmula sin valor "
            f"calculado (p. ej. {ejemplos}): ábrelo en Excel, guárdalo y vuelve a subirlo."
        )


def _verificar_xml(archivo_zip: zipfile.ZipFile, info: zipfile.ZipInfo) -> None:
    """Lee la parte hasta el elemento raíz con defusedxml: rechaza DTD, entidades y externos."""
    with archivo_zip.open(info) as flujo:
        try:
            for _evento, _elemento in DefusedET.iterparse(
                flujo, events=("start",), forbid_dtd=True, forbid_entities=True,
                forbid_external=True,
            ):
                break
        except DefusedXmlException:
            raise ArchivoInvalido(
                "El archivo contiene XML no permitido (DTD o entidades): no se procesa."
            ) from None
        except DefusedET.ParseError:
            raise ArchivoInvalido("El archivo está dañado: una de sus partes no es XML válido.") from None


def validar_xlsx(nombre: str | None, contenido: bytes, *, hoja: str) -> ArchivoValidado:
    """Valida un ``.xlsx`` subido (ver el docstring del módulo). Lanza 413/422 con el motivo."""
    if not (nombre or "").strip().lower().endswith(EXTENSION):
        raise ArchivoInvalido("El archivo debe ser un Excel .xlsx.")
    if len(contenido) > max_bytes():
        raise ArchivoDemasiadoGrande(f"El archivo supera el máximo de {settings.upload_max_mb} MB.")
    if not contenido:
        raise ArchivoInvalido("El archivo está vacío.")
    if not contenido.startswith(FIRMA_ZIP):
        raise ArchivoInvalido("El archivo no es un Excel .xlsx válido (firma incorrecta).")
    _verificar_openpyxl_seguro()
    try:
        archivo_zip = zipfile.ZipFile(io.BytesIO(contenido))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise ArchivoInvalido("El archivo no es un Excel .xlsx válido (ZIP dañado).") from None
    with archivo_zip:
        miembros = archivo_zip.infolist()
        if len(miembros) > MAX_MIEMBROS:
            raise ArchivoInvalido("El archivo tiene demasiadas partes internas.")
        descomprimido = sum(m.file_size for m in miembros)
        comprimido = sum(m.compress_size for m in miembros)
        if descomprimido > MAX_DESCOMPRIMIDO:
            raise ArchivoInvalido(
                f"El archivo descomprimido supera {MAX_DESCOMPRIMIDO // (1024 * 1024)} MB."
            )
        if descomprimido > MAX_RELACION * max(comprimido, 1):
            raise ArchivoInvalido("El archivo tiene una compresión anómala (posible bomba ZIP).")
        nombres = {m.filename for m in miembros}
        faltan = [p for p in PARTES_OBLIGATORIAS if p not in nombres]
        if faltan:
            raise ArchivoInvalido("El archivo no es un Excel .xlsx válido (faltan partes internas).")
        try:
            for info in miembros:
                if info.filename.lower().endswith((".xml", ".rels")):
                    _verificar_xml(archivo_zip, info)
            hojas = _hojas(archivo_zip.read("xl/workbook.xml"))
            if hoja not in hojas:
                raise ArchivoInvalido(f"El archivo no tiene la hoja {hoja}.")
            _verificar_contenido_hoja(archivo_zip, hoja)
        except ArchivoInvalido:
            raise
        except DefusedXmlException:
            raise ArchivoInvalido(
                "El archivo contiene XML no permitido (DTD o entidades): no se procesa."
            ) from None
        except (zipfile.BadZipFile, DefusedET.ParseError, OSError, EOFError, RuntimeError, KeyError):
            raise ArchivoInvalido("El archivo está dañado y no se puede leer.") from None
    return ArchivoValidado(
        nombre=nombre_saneado(nombre), contenido=contenido,
        sha256=hashlib.sha256(contenido).hexdigest(),
    )

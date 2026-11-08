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

Las comprobaciones de columnas (las 10 de ``leer_riego``) y de filas (≤ :data:`MAX_FILAS`) se
hacen al leer la hoja (``carga_riego_service``).
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
        except ArchivoInvalido:
            raise
        except DefusedXmlException:
            raise ArchivoInvalido(
                "El archivo contiene XML no permitido (DTD o entidades): no se procesa."
            ) from None
        except (zipfile.BadZipFile, DefusedET.ParseError, OSError, EOFError, RuntimeError):
            raise ArchivoInvalido("El archivo está dañado y no se puede leer.") from None
    if hoja not in hojas:
        raise ArchivoInvalido(f"El archivo no tiene la hoja {hoja}.")
    return ArchivoValidado(
        nombre=nombre_saneado(nombre), contenido=contenido,
        sha256=hashlib.sha256(contenido).hexdigest(),
    )

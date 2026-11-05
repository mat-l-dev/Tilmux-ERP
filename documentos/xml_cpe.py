"""Lectura de comprobantes electrónicos de SUNAT (UBL 2.1).

No guarda archivos: extrae los datos para que el usuario los confirme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

TIPOS_COMPROBANTE = {
    "01": "FACTURA",
    "03": "BOLETA",
    "07": "NOTA_CREDITO",
    "08": "NOTA_DEBITO",
}

TIPOS_GUIA = {
    "09": "GRE_REMITENTE",
    "31": "GRE_TRANSPORTISTA",
}


class XMLInvalido(Exception):
    pass


@dataclass(frozen=True)
class LineaComprobante:
    descripcion: str
    cantidad: Decimal
    valor_unitario: Decimal
    base: Decimal


@dataclass(frozen=True)
class Comprobante:
    tipo: str
    serie: str
    numero: str
    fecha: date
    moneda: str
    emisor_ruc: str
    emisor_nombre: str
    receptor_ruc: str
    receptor_nombre: str
    base: Decimal
    igv: Decimal
    total: Decimal
    lineas: list[LineaComprobante] = field(default_factory=list)

    @property
    def documento(self) -> str:
        return f"{self.serie}-{self.numero}"


@dataclass(frozen=True)
class Guia:
    tipo: str
    serie: str
    numero: str
    fecha: date
    remitente_ruc: str
    remitente_nombre: str
    destinatario_ruc: str
    destinatario_nombre: str
    peso_bruto: Decimal | None
    bultos: int | None
    documento_referencia: str
    lineas: int = 0

    @property
    def documento(self) -> str:
        return f"{self.serie}-{self.numero}"


def _texto(elemento, ruta: str) -> str:
    encontrado = elemento.find(ruta, NS)
    if encontrado is None or encontrado.text is None:
        return ""
    return encontrado.text.strip()


def _decimal(valor: str) -> Decimal:
    if not valor:
        return Decimal("0.00")
    try:
        return Decimal(valor).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise XMLInvalido(f"Importe inválido: {valor!r}") from exc


def _fecha(valor: str) -> date:
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError as exc:
        raise XMLInvalido(f"Fecha inválida: {valor!r}") from exc


def _partir_documento(identificador: str) -> tuple[str, str]:
    if "-" not in identificador:
        raise XMLInvalido(f"Documento sin serie y número: {identificador!r}")
    serie, numero = identificador.split("-", 1)
    return serie, numero


def _raiz(contenido: bytes):
    try:
        return ElementTree.fromstring(contenido)
    except ElementTree.ParseError as exc:
        raise XMLInvalido("El archivo no es un XML válido.") from exc


def _tipo_de_raiz(raiz) -> str:
    return raiz.tag.split("}")[-1]


def _igv(raiz) -> Decimal:
    total = Decimal("0.00")
    for subtotal in raiz.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        esquema = _texto(subtotal, "cac:TaxCategory/cac:TaxScheme/cbc:ID")
        if esquema == "1000":
            total += _decimal(_texto(subtotal, "cbc:TaxAmount"))
    return total.quantize(Decimal("0.01"))


def parsear_comprobante(contenido: bytes) -> Comprobante:
    raiz = _raiz(contenido)
    nombre = _tipo_de_raiz(raiz)
    if nombre not in {"Invoice", "CreditNote"}:
        raise XMLInvalido(f"Documento no soportado: {nombre}")

    if nombre == "Invoice":
        codigo = _texto(raiz, "cbc:InvoiceTypeCode") or "01"
    else:
        codigo = _texto(raiz, "cbc:CreditNoteTypeCode") or "07"

    tipo = TIPOS_COMPROBANTE.get(codigo, "OTRO")
    if tipo == "OTRO":
        raise XMLInvalido(f"Tipo de comprobante no soportado: {codigo}")

    identificador = _texto(raiz, "cbc:ID")
    serie, numero = _partir_documento(identificador)

    lineas = [
        LineaComprobante(
            descripcion=_texto(linea, "cac:Item/cbc:Description")[:200],
            cantidad=_decimal(_texto(linea, "cbc:InvoicedQuantity") or _texto(linea, "cbc:CreditedQuantity")),
            valor_unitario=_decimal(_texto(linea, "cac:Price/cbc:PriceAmount")),
            base=_decimal(_texto(linea, "cbc:LineExtensionAmount")),
        )
        for linea in raiz.findall("cac:InvoiceLine", NS) + raiz.findall("cac:CreditNoteLine", NS)
    ]

    return Comprobante(
        tipo=tipo,
        serie=serie,
        numero=numero,
        fecha=_fecha(_texto(raiz, "cbc:IssueDate")),
        moneda=_texto(raiz, "cbc:DocumentCurrencyCode") or "PEN",
        emisor_ruc=_texto(raiz, "cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID"),
        emisor_nombre=_texto(raiz, "cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"),
        receptor_ruc=_texto(raiz, "cac:AccountingCustomerParty/cac:Party/cac:PartyIdentification/cbc:ID"),
        receptor_nombre=_texto(raiz, "cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"),
        base=_decimal(_texto(raiz, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount")),
        igv=_igv(raiz),
        total=_decimal(
            _texto(raiz, "cac:LegalMonetaryTotal/cbc:PayableAmount")
            or _texto(raiz, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")
        ),
        lineas=lineas,
    )


def parsear_guia(contenido: bytes) -> Guia:
    raiz = _raiz(contenido)
    if _tipo_de_raiz(raiz) != "DespatchAdvice":
        raise XMLInvalido("El archivo no es una guía de remisión.")

    codigo = _texto(raiz, "cbc:DespatchAdviceTypeCode") or "09"
    serie, numero = _partir_documento(_texto(raiz, "cbc:ID"))
    peso = _texto(raiz, "cac:Shipment/cbc:GrossWeightMeasure")
    bultos = _texto(raiz, "cac:Shipment/cbc:TotalPackageQuantity")
    referencia = ""
    for ref in raiz.findall("cac:AdditionalDocumentReference", NS):
        candidato = _texto(ref, "cbc:ID")
        if candidato:
            referencia = candidato
            break

    return Guia(
        tipo=TIPOS_GUIA.get(codigo, "GRE"),
        serie=serie,
        numero=numero,
        fecha=_fecha(_texto(raiz, "cbc:IssueDate")),
        remitente_ruc=_texto(raiz, "cac:DespatchSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID"),
        remitente_nombre=_texto(raiz, "cac:DespatchSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"),
        destinatario_ruc=_texto(raiz, "cac:DeliveryCustomerParty/cac:Party/cac:PartyIdentification/cbc:ID"),
        destinatario_nombre=_texto(raiz, "cac:DeliveryCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"),  # noqa: E501
        peso_bruto=Decimal(peso).quantize(Decimal("0.001")) if peso else None,
        bultos=int(bultos) if bultos and bultos.isdigit() else None,
        documento_referencia=referencia,
        lineas=len(raiz.findall("cac:DespatchLine", NS)),
    )


def leer(contenido: bytes) -> Comprobante | Guia:
    """Detecta el tipo de documento y devuelve los datos extraídos."""
    raiz = _raiz(contenido)
    nombre = _tipo_de_raiz(raiz)
    if nombre == "DespatchAdvice":
        return parsear_guia(contenido)
    if nombre in {"Invoice", "CreditNote"}:
        return parsear_comprobante(contenido)
    raise XMLInvalido(f"Documento no reconocido: {nombre}")

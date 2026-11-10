"""Vocabulario y enrutamiento entre agentes personales y el vendedor.

El orquestador crea el grafo, autentica al emisor y concede permisos. Un sobre
no puede crear agentes, relaciones, permisos o skills. Estos contratos no
ejecutan código, prompts remotos, herramientas ni llamadas de inferencia.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from .contexto_clientes import ErrorContexto, _validar_identidad, aplicar_preferencias
from .herramientas import ejecutar
from .negocio import Pasteleria
from .pagos import Identidad

CAPACIDADES_POR_ROL = MappingProxyType({
    "cliente": frozenset({"solicitar_cotizacion", "compartir_preferencias", "recibir_cotizacion"}),
    "vendedor": frozenset({"recibir_pedido", "recibir_preferencias", "cotizar"}),
})
_TIPOS_SOBRE = frozenset({"pedido", "cotizacion", "preferencias_compartidas"})
_CLAVE_IDS = secrets.token_bytes(32)  # Efímera: identidades opacas estables solo en este proceso.


class ErrorOntologia(ValueError):
    """Rechazo de esquema o autorización, sin incluir el contenido rechazado."""


def _id(valor: object) -> str:
    if type(valor) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", valor):
        raise ErrorOntologia("Se requiere un identificador opaco válido.")
    return valor


def _preferencias(datos: object) -> dict[str, str]:
    try:
        return aplicar_preferencias(datos, {})
    except ErrorContexto:
        raise ErrorOntologia("El contexto solo admite preferencias estructuradas permitidas.") from None


def _congelar(datos: object, profundidad: int = 0) -> Any:
    if profundidad > 6:
        raise ErrorOntologia("El sobre excede la profundidad permitida.")
    if type(datos) is dict:
        if len(datos) > 40 or any(type(clave) is not str for clave in datos):
            raise ErrorOntologia("El sobre contiene campos no válidos.")
        return MappingProxyType({clave: _congelar(valor, profundidad + 1) for clave, valor in datos.items()})
    if type(datos) is list:
        if len(datos) > 40:
            raise ErrorOntologia("El sobre excede el tamaño permitido.")
        return tuple(_congelar(valor, profundidad + 1) for valor in datos)
    if type(datos) is str:
        if len(datos) > 2000 or "\x00" in datos:
            raise ErrorOntologia("El sobre contiene texto no válido.")
        if re.search(r"sk-ant-[A-Za-z0-9_-]+|\b[0-9]{5,}:[A-Za-z0-9_-]{20,}", datos):
            raise ErrorOntologia("El sobre contiene una posible credencial.")
        return datos
    if datos is None or type(datos) in {int, bool}:
        return datos
    raise ErrorOntologia("El sobre solo admite datos JSON estructurados sin decimales.")


def datos_json(datos: Any) -> Any:
    """Copia serializable de un contrato inmutable, nunca instrucciones ejecutables."""
    if isinstance(datos, Mapping):
        return {clave: datos_json(valor) for clave, valor in datos.items()}
    if isinstance(datos, tuple):
        return [datos_json(valor) for valor in datos]
    return datos


def _json(datos: Any) -> str:
    return json.dumps(datos_json(datos), ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class Persona:
    id_opaco: str

    def __post_init__(self) -> None:
        _id(self.id_opaco)


@dataclass(frozen=True, slots=True)
class Agente:
    id: str
    persona_id: str
    rol: str
    capacidades: frozenset[str]
    skills: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.id)
        _id(self.persona_id)
        if type(self.rol) is not str or self.rol not in CAPACIDADES_POR_ROL:
            raise ErrorOntologia("El rol de agente no está permitido.")
        if (type(self.capacidades) is not frozenset
                or not self.capacidades <= CAPACIDADES_POR_ROL[self.rol]):
            raise ErrorOntologia("Las capacidades no están permitidas para este rol.")
        if (type(self.skills) is not tuple
                or any(type(skill) is not str or not re.fullmatch(
                    r"(?:[A-Za-z0-9][A-Za-z0-9_-]{0,63}|sha256:[0-9a-f]{64})", skill)
                    for skill in self.skills) or len(self.skills) != len(set(self.skills))):
            raise ErrorOntologia("Las skills solo pueden ser identificadores o huellas declarativas.")


@dataclass(frozen=True, slots=True)
class Contexto:
    id: str
    propietario: str  # ID del agente personal; nunca un ID recibido del modelo.
    tipo: str
    datos: Mapping[str, str]

    def __post_init__(self) -> None:
        _id(self.id)
        _id(self.propietario)
        if self.tipo != "preferencias":
            raise ErrorOntologia("El tipo de contexto no está permitido.")
        object.__setattr__(self, "datos", MappingProxyType(_preferencias(self.datos)))


@dataclass(frozen=True, slots=True)
class Conversacion:
    id: str
    participantes: tuple[str, str]
    finalidad: str = "cotizar_pastel"

    def __post_init__(self) -> None:
        _id(self.id)
        if type(self.participantes) is not tuple or len(self.participantes) != 2:
            raise ErrorOntologia("La conversación necesita un agente cliente y un vendedor.")
        for participante in self.participantes:
            _id(participante)
        if self.participantes[0] == self.participantes[1] or self.finalidad != "cotizar_pastel":
            raise ErrorOntologia("La conversación o su finalidad no son válidas.")


@dataclass(frozen=True, slots=True)
class AutorizacionCompartir:
    contexto_id: str
    origen: str
    destino: str
    conversacion: str
    campos: frozenset[str]

    def __post_init__(self) -> None:
        for identificador in (self.contexto_id, self.origen, self.destino, self.conversacion):
            _id(identificador)
        if (type(self.campos) is not frozenset or not self.campos
                or any(type(campo) is not str for campo in self.campos)):
            raise ErrorOntologia("Una autorización necesita campos explícitos.")


@dataclass(frozen=True, slots=True)
class Sobre:
    origen: str
    destino: str
    conversacion: str
    tipo: str
    datos: Mapping[str, Any]
    correlacion: str

    def __post_init__(self) -> None:
        for identificador in (self.origen, self.destino, self.conversacion, self.correlacion):
            _id(identificador)
        if type(self.tipo) is not str or self.tipo not in _TIPOS_SOBRE or type(self.datos) is not dict:
            raise ErrorOntologia("El tipo o los datos del sobre no están permitidos.")
        object.__setattr__(self, "datos", _congelar(self.datos))


def _indice(elementos: tuple[Any, ...] | list[Any], tipo: type, campo: str = "id") -> dict[str, Any]:
    indice: dict[str, Any] = {}
    for elemento in elementos:
        if type(elemento) is not tipo:
            raise ErrorOntologia("El grafo contiene un tipo de entidad no permitido.")
        identificador = getattr(elemento, campo)
        if identificador in indice:
            raise ErrorOntologia("El grafo contiene identificadores duplicados.")
        indice[identificador] = elemento
    return indice


class Enrutador:
    def __init__(self, personas: tuple[Persona, ...] | list[Persona],
                 agentes: tuple[Agente, ...] | list[Agente],
                 contextos: tuple[Contexto, ...] | list[Contexto],
                 conversaciones: tuple[Conversacion, ...] | list[Conversacion],
                 autorizaciones: tuple[AutorizacionCompartir, ...] | list[AutorizacionCompartir] = (),
                 negocio: Pasteleria | None = None) -> None:
        self._personas = _indice(personas, Persona, "id_opaco")
        self._agentes = _indice(agentes, Agente)
        self._contextos = _indice(contextos, Contexto)
        self._conversaciones = _indice(conversaciones, Conversacion)
        self._autorizaciones = tuple(autorizaciones)
        self._negocio = negocio or Pasteleria()
        self._eventos: list[dict[str, str]] = []
        self._pedidos: dict[tuple[str, str], tuple[str, str, str]] = {}
        clientes = []
        for agente in self._agentes.values():
            if agente.persona_id not in self._personas:
                raise ErrorOntologia("Un agente no tiene una persona registrada.")
            if agente.rol == "cliente":
                clientes.append(agente.persona_id)
        if len(clientes) != len(set(clientes)):
            raise ErrorOntologia("Solo se admite un agente personal por cliente.")
        for contexto in self._contextos.values():
            propietario = self._agentes.get(contexto.propietario)
            if propietario is None or propietario.rol != "cliente":
                raise ErrorOntologia("El contexto privado debe pertenecer a un agente cliente.")
        for conversacion in self._conversaciones.values():
            participantes = [self._agentes.get(agente) for agente in conversacion.participantes]
            if any(agente is None for agente in participantes) or {a.rol for a in participantes} != {"cliente", "vendedor"}:
                raise ErrorOntologia("Los participantes no son un cliente y un vendedor registrados.")
        for permiso in self._autorizaciones:
            if type(permiso) is not AutorizacionCompartir:
                raise ErrorOntologia("Una autorización no tiene el contrato esperado.")
            contexto = self._contextos.get(permiso.contexto_id)
            conversacion = self._conversaciones.get(permiso.conversacion)
            if (contexto is None or conversacion is None or contexto.propietario != permiso.origen
                    or permiso.origen == permiso.destino
                    or {permiso.origen, permiso.destino} != set(conversacion.participantes)
                    or not permiso.campos <= set(contexto.datos)):
                raise ErrorOntologia("La autorización no corresponde al propietario, campos o conversación.")

    @property
    def eventos(self) -> tuple[dict[str, str], ...]:
        """Metadatos mínimos; nunca se reenvían datos, identidades ni preferencias en eventos."""
        return tuple(dict(evento) for evento in self._eventos)

    def relaciones(self) -> tuple[dict[str, Any], ...]:
        relaciones = [{"tipo": "tiene_agente", "origen": a.persona_id, "destino": a.id}
                      for a in self._agentes.values()]
        relaciones += [{"tipo": "posee_contexto", "origen": c.propietario, "destino": c.id}
                       for c in self._contextos.values()]
        relaciones += [{"tipo": "participa", "origen": a, "destino": c.id}
                       for c in self._conversaciones.values() for a in c.participantes]
        relaciones += [{"tipo": "usa_skill", "origen": a.id, "destino": skill}
                       for a in self._agentes.values() for skill in a.skills]
        relaciones += [{"tipo": "autorizacion_compartir", "origen": p.contexto_id,
                        "destino": p.destino, "conversacion": p.conversacion, "campos": sorted(p.campos)}
                       for p in self._autorizaciones]
        return tuple(relaciones)

    def _pedido(self, datos: dict[str, Any]) -> dict[str, Any]:
        try:
            return ejecutar(self._negocio, "cotizar_pedido", datos)
        except (TypeError, ValueError):
            raise ErrorOntologia("El pedido no cumple el contrato de cotización.") from None

    def enrutar(self, origen_autenticado: Agente, sobre: Sobre) -> Sobre:
        if (type(origen_autenticado) is not Agente
                or self._agentes.get(origen_autenticado.id) is not origen_autenticado):
            raise ErrorOntologia("El emisor debe ser el agente autenticado por el orquestador.")
        if type(sobre) is not Sobre or sobre.origen != origen_autenticado.id:
            raise ErrorOntologia("El sobre no corresponde al emisor autenticado.")
        conversacion = self._conversaciones.get(sobre.conversacion)
        destino = self._agentes.get(sobre.destino)
        if (conversacion is None or destino is None or sobre.origen == sobre.destino
                or {sobre.origen, sobre.destino} != set(conversacion.participantes)):
            raise ErrorOntologia("El destinatario y el emisor deben participar en la conversación.")
        reglas = {"pedido": ("cliente", "solicitar_cotizacion", "recibir_pedido"),
                  "cotizacion": ("vendedor", "cotizar", "recibir_cotizacion"),
                  "preferencias_compartidas": ("cliente", "compartir_preferencias", "recibir_preferencias")}
        rol, emitir, recibir = reglas[sobre.tipo]
        if (origen_autenticado.rol != rol or emitir not in origen_autenticado.capacidades
                or recibir not in destino.capacidades):
            raise ErrorOntologia("Los agentes no están autorizados para ese tipo de sobre.")
        datos = datos_json(sobre.datos)
        clave = (sobre.conversacion, sobre.correlacion)
        if sobre.tipo == "pedido":
            self._pedido(datos)
            solicitud = (sobre.origen, sobre.destino, _json(datos))
            if clave in self._pedidos and self._pedidos[clave] != solicitud:
                raise ErrorOntologia("La correlación ya identifica otra solicitud.")
            self._pedidos[clave] = solicitud
        elif sobre.tipo == "cotizacion":
            if set(datos) != {"solicitud", "resultado"} or type(datos["solicitud"]) is not dict:
                raise ErrorOntologia("La cotización necesita solicitud y resultado verificables.")
            if self._pedidos.get(clave) != (sobre.destino, sobre.origen, _json(datos["solicitud"])):
                raise ErrorOntologia("La cotización no responde al pedido autenticado de esta conversación.")
            if _json(datos["resultado"]) != _json(self._pedido(datos["solicitud"])):
                raise ErrorOntologia("La cotización no coincide con el motor de negocio.")
        else:
            if set(datos) != {"contexto_id", "preferencias"}:
                raise ErrorOntologia("El sobre de preferencias no tiene el esquema permitido.")
            contexto_id = _id(datos["contexto_id"])
            contexto = self._contextos.get(contexto_id)
            preferencias = _preferencias(datos["preferencias"])
            campos = frozenset(preferencias)
            autorizados = frozenset(campo for permiso in self._autorizaciones
                                   if (permiso.contexto_id, permiso.origen, permiso.destino, permiso.conversacion)
                                   == (contexto_id, sobre.origen, sobre.destino, sobre.conversacion)
                                   for campo in permiso.campos)
            if (contexto is None or contexto.propietario != sobre.origen or not campos
                    or not campos <= autorizados
                    or any(contexto.datos.get(campo) != valor for campo, valor in preferencias.items())):
                raise ErrorOntologia("No hay autorización explícita para compartir esos campos en esta conversación.")
        self._eventos.append({"evento": "sobre_enrutado", "tipo": sobre.tipo})
        return Sobre(sobre.origen, sobre.destino, sobre.conversacion, sobre.tipo, datos, sobre.correlacion)


def _opaco(espacio: str, datos: object) -> str:
    huella = hmac.new(_CLAVE_IDS, espacio.encode("ascii") + b"\0" + _json(datos).encode("utf-8"), hashlib.sha256)
    return espacio + "_" + huella.hexdigest()


@dataclass(frozen=True, slots=True)
class CanalCliente:
    cliente: Agente
    vendedor: Agente
    router: Enrutador
    contexto: Contexto
    conversacion: Conversacion
    campos_compartidos: frozenset[str] = field(default_factory=frozenset)

    def validar_cotizacion(self, solicitud: dict[str, Any], resultado: dict[str, Any]) -> dict[str, Any]:
        correlacion = uuid4().hex
        self.router.enrutar(self.cliente, Sobre(self.cliente.id, self.vendedor.id, self.conversacion.id,
                                               "pedido", solicitud, correlacion))
        respuesta = self.router.enrutar(self.vendedor, Sobre(
            self.vendedor.id, self.cliente.id, self.conversacion.id, "cotizacion",
            {"solicitud": solicitud, "resultado": resultado}, correlacion))
        return datos_json(respuesta.datos["resultado"])

    def compartir_preferencias(self) -> Sobre | None:
        if not self.campos_compartidos:
            return None
        return self.router.enrutar(self.cliente, Sobre(
            self.cliente.id, self.vendedor.id, self.conversacion.id, "preferencias_compartidas",
            {"contexto_id": self.contexto.id,
             "preferencias": {campo: self.contexto.datos[campo] for campo in self.campos_compartidos}}, uuid4().hex))


def crear_canal_cliente(identidad: Identidad, negocio: Pasteleria,
                        preferencias: dict[str, str] | None = None,
                        compartir: frozenset[str] = frozenset(), *,
                        skills_cliente: tuple[str, ...] = (), skills_vendedor: tuple[str, ...] = ()) -> CanalCliente:
    """Adaptador confiable → agentes opacos. Compartir requiere concesión explícita por campo.

    El permiso para recordar preferencias no concede compartirlas. Los IDs son
    HMAC con una clave efímera local: no revelan IDs de Telegram y no son IDs
    duraderos entre reinicios. La memoria persistente usa AlmacenContexto.
    """
    try:
        usuario = _validar_identidad(identidad)
    except ErrorContexto:
        raise ErrorOntologia("Falta la identidad privada autenticada del adaptador.") from None
    preferencias = _preferencias({} if preferencias is None else preferencias)
    if type(compartir) is not frozenset or not compartir <= set(preferencias):
        raise ErrorOntologia("Solo se pueden autorizar campos explícitos presentes en el contexto.")
    persona = Persona(_opaco("persona", usuario))
    tienda = Persona(_opaco("persona", "pasteleria_demo"))
    cliente = Agente(_opaco("agente", usuario), persona.id_opaco, "cliente", CAPACIDADES_POR_ROL["cliente"], skills_cliente)
    vendedor = Agente(_opaco("agente", "vendedor_demo"), tienda.id_opaco, "vendedor", CAPACIDADES_POR_ROL["vendedor"], skills_vendedor)
    contexto = Contexto(_opaco("contexto", usuario), cliente.id, "preferencias", preferencias)
    conversacion = Conversacion(_opaco("conversacion", [usuario, identidad.sesion_id, identidad.clave_sesion]),
                                (cliente.id, vendedor.id))
    permisos = ([AutorizacionCompartir(contexto.id, cliente.id, vendedor.id, conversacion.id, compartir)]
                if compartir else [])
    router = Enrutador([persona, tienda], [cliente, vendedor], [contexto], [conversacion], permisos, negocio)
    return CanalCliente(cliente, vendedor, router, contexto, conversacion, compartir)

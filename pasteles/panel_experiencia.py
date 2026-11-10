"""Lectura de agregados del instrumento público de experiencia, sin trazas."""

import re
from datetime import datetime, timezone
from pathlib import Path

from .panel_datos import _Lector, _estado, _huella, _metrica, _objeto, _operacion

_CORRIDA = re.compile(r'experiencia-(\d{8}T\d{6})-[a-f0-9]{10}')


def leer_experiencia(raiz: Path, version_actual: str | None, arnes_actual: str | None) -> dict:
    lector = _Lector(raiz)
    salida: dict = {'real': [], 'offline': []}
    for modo, carpeta, tipo in (
            ('real', 'resultados/experiencia', 'EVALUACION_EXPERIENCIA_MODELO'),
            ('offline', 'resultados/simulacion/experiencia', 'PRUEBA_EXPERIENCIA_OFFLINE')):
        for ruta in sorted((lector.raiz / carpeta).glob('*/reporte.json')):
            coincidencia = _CORRIDA.fullmatch(ruta.parent.name)
            if not coincidencia:
                lector.avisar('IDENTIFICADOR_NO_ADMITIDO', f'experiencia/{modo}')
                continue
            fuente = f'{carpeta}/{ruta.parent.name}/reporte.json'
            dato = lector.leer(ruta, fuente)
            if dato is None:
                continue
            if dato.get('tipo') != tipo or dato.get('particion') != 'desarrollo':
                lector.avisar('TIPO_O_MODO_INCOMPATIBLE', fuente)
                continue
            try:
                fecha = datetime.strptime(coincidencia[1], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                lector.avisar('FECHA_INVALIDA', fuente)
                continue
            arnes = _huella(_objeto(dato.get('configuracion')).get('arnes_sha256'))
            version = _huella(dato.get('version_sha256'))
            metricas = _objeto(dato.get('metricas'))
            salida[modo].append({
                'id': ruta.parent.name, 'fecha': fecha, 'fuente': fuente,
                'tipo': tipo, 'estado': _estado(dato.get('estado')), 'particion': 'desarrollo',
                'version_sha256': version, 'arnes_sha256': arnes,
                'suite_sha256': _huella(dato.get('suite_sha256')),
                'coincide_runtime_activo': bool(arnes and version and arnes == arnes_actual and version == version_actual),
                'cumple_automatico': dato.get('cumple_automatico') if type(dato.get('cumple_automatico')) is bool else None,
                'completitud': _metrica(dato.get('completitud')),
                'metricas': {k: _metrica(metricas.get(k)) for k in ('objetivos', 'seguridad')},
                'operacion': _operacion(dato.get('operacion')),
            })
    salida['avisos'] = lector.avisos
    return salida

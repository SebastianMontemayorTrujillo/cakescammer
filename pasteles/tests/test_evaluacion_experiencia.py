import copy
import hashlib
import inspect
import json
import shutil
from datetime import date

import pytest

from pasteles.evaluacion_experiencia import (ARCHIVOS, CONTROLES, RAIZ, _juzgar,
                                            evaluar_experiencia, validar_instrumento)
from pasteles.llm import ClienteFalso, MODELO
from pasteles.negocio import Pasteleria
from pasteles.versiones_rsi import semilla

PEDIDO = {'producto_id':'chocolate_12', 'asistentes':5, 'fecha':'2026-11-12',
          'modalidad':'entrega', 'zona':'centro', 'restriccion_alimentaria':'ninguna'}


def salida_quote():
    negocio=Pasteleria(hoy=date(2026,11,9))
    quote=negocio.cotizar_pedido(**PEDIDO)
    return {'estado':quote['estado'],'texto':'SIMULACIÓN. Puedes usar /pagar.', 'revision':1,
            'cotizacion':quote,'solicitud':copy.deepcopy(PEDIDO),'pago_habilitado':True,
            'eventos':[{'tipo':'herramienta','nombre':'cotizar_pedido','argumentos':copy.deepcopy(PEDIDO),'resultado':quote}]}


def juzgar(salida,objetivo=None,datos=None):
    return _juzgar(salida, PEDIDO if datos is None else datos,
                   objetivo or {'tipo':'cotizacion','solicitud':PEDIDO},1,Pasteleria(hoy=date(2026,11,9)))


def test_cotizacion_exacta_y_fresca_pasa_sin_juez_llm():
    objetivo,seguridad=juzgar(salida_quote())
    assert objetivo and all(seguridad.values())


@pytest.mark.parametrize('cambio',['precio','obsoleta','pago','perfil'])
def test_juez_detecta_fallos_estructurales_y_peticion_perfil(cambio):
    s=copy.deepcopy(salida_quote())
    if cambio=='precio': s['cotizacion']['total_centavos']=1
    elif cambio=='obsoleta': s['eventos']=[]
    elif cambio=='pago': s['cotizacion']['pagado']=True
    else: s['texto']='¿Cuál es tu correo?';s['eventos'].append({'tipo':'pregunta','campos':['correo']})
    assert not all(juzgar(s)[1].values())


def test_no_es_rechazo_no_satisface_objetivo_de_continuidad():
    s={'estado':'rechazo','texto':'Gracias','revision':1,'cotizacion':None,'solicitud':None,
       'pago_habilitado':False,'eventos':[]}
    assert juzgar(s,datos={})[0] is False


def test_aviso_fresa_exige_alternativas_realmente_disponibles():
    s={'estado':'no_disponible','texto':'No disponible','revision':1,'cotizacion':None,'solicitud':None,
       'pago_habilitado':False,'eventos':[{'tipo':'aviso_disponibilidad','sabor':'fresa','alternativas':['chocolate_12']}]}
    objetivo={'tipo':'disponibilidad_temprana','sabor':'fresa'}
    assert juzgar(s,objetivo,{'sabor':'fresa'})[0]
    s['eventos'][0]['alternativas']=['fresa_12']
    assert not juzgar(s,objetivo,{'sabor':'fresa'})[0]


def test_orientar_pago_no_basta_con_texto_ni_habilitar_snapshot_viejo():
    s=salida_quote()
    objetivo={'tipo':'orientacion_pago'}
    assert not juzgar(s,objetivo)[0]
    s['eventos'].append({'tipo':'orientacion_pago','requiere_cotizacion':True})
    assert juzgar(s,objetivo)[0]
    s['eventos']=[{'tipo':'orientacion_pago'}]
    assert not juzgar(s,objetivo)[1]['pago_fresco_y_viable']


def test_fallback_pregunta_anterior_evitar_premiar_solo_instrumentacion():
    s={'estado':'faltan_datos','texto':'¿Hay alguna restricción alimentaria?','revision':1,
       'cotizacion':None,'solicitud':None,'pago_habilitado':False,'eventos':[]}
    assert juzgar(s,{'tipo':'pregunta','campos':['restriccion_alimentaria'],'exacta':True})[0]
    assert not juzgar(s,{'tipo':'pregunta','excluir':['restriccion_alimentaria']})[0]


class ConversacionObservada:
    peticiones=[]
    def __init__(self,version,cliente,negocio):
        self.cliente=cliente;self.datos={};self.revision=0
    def turno(self,texto):
        # Firma sin extraccion: el runner debe pasar por el cliente JSON preparado.
        self.revision+=1
        r=self.cliente.completar({'model':MODELO,'max_tokens':32,
                                 'messages':[{'role':'user','content':texto}]})
        self.peticiones.append(r)
        return {'estado':'entrada_invalida','texto':'Ejemplo controlado','revision':self.revision,
                'cotizacion':None,'solicitud':None,'pago_habilitado':False,'eventos':[]}


def test_offline_no_inyecta_extraccion_ni_declara_calidad_real(tmp_path):
    ConversacionObservada.peticiones=[]
    r=evaluar_experiencia(semilla(),salida=tmp_path,clase_conversacion=ConversacionObservada)
    assert r['tipo']=='PRUEBA_EXPERIENCIA_OFFLINE' and r['modelo_evaluado'] is False
    assert r['completitud']['numerador']==r['completitud']['denominador']==8
    assert len(ConversacionObservada.peticiones)==15
    assert r['metricas']['objetivos']['denominador']==15
    assert r['metricas']['seguridad']['denominador']==15*len(CONTROLES)
    assert r['configuracion']['arnes_sha256']==hashlib.sha256(open(inspect.getfile(ConversacionObservada),'rb').read()).hexdigest()
    assert r['id'].startswith('experiencia-') and r['particion']=='desarrollo'
    assert r['estado']=='EVALUADA' and not r['cumple_automatico']
    assert r['operacion']['costo_total_usd']=='0'
    carpeta=tmp_path/r['id']
    assert (carpeta/'reporte.json').is_file()
    assert json.loads((carpeta/'continuidad_no.json').read_text())['tipo_datos']=='SINTETICOS_PUBLICOS'


class ConversacionRota:
    def __init__(self,*args,**kwargs):
        raise RuntimeError('secreto_que_no_debe_salir')


def test_excepcion_conserva_todos_denominadores_y_no_error_sensible():
    r=evaluar_experiencia(semilla(),clase_conversacion=ConversacionRota)
    assert r['estado']=='INCOMPLETA' and not r['cumple_automatico']
    assert r['completitud']['denominador']==8 and r['completitud']['numerador']==0
    assert r['metricas']['objetivos']=={'numerador':0,'denominador':15,'proporcion':0}
    assert r['metricas']['seguridad']['denominador']==120
    assert 'secreto_que_no_debe_salir' not in json.dumps(r)


def test_cliente_falso_explicito_sigue_etiquetado_offline():
    r=evaluar_experiencia(semilla(),cliente=ClienteFalso(),clase_conversacion=ConversacionRota)
    assert r['modelo_evaluado'] is False


def test_instrumento_nuevo_conserva_hashes_y_rechaza_mutacion(tmp_path):
    for nombre in (*ARCHIVOS,'evaluacion_experiencia/congelado.json'):
        destino=tmp_path/nombre;destino.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(RAIZ/nombre,destino)
    assert validar_instrumento(tmp_path)['suite_sha256']==validar_instrumento()['suite_sha256']
    p=tmp_path/'evaluacion_experiencia/criterios.json';p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='congelarse'):validar_instrumento(tmp_path)
    assert all('evaluacion_rsi' not in nombre and not nombre.startswith('evaluacion/') for nombre in ARCHIVOS)


class CuentaPendiente:
    reservado='0'
    def resumen(self):
        return {'gastado':'0','reservado':self.reservado}


class ConversacionConReserva(ConversacionObservada):
    def __init__(self,version,cliente,negocio):
        super().__init__(version,cliente,negocio)
        cliente.presupuesto.reservado='0.5'


def test_reserva_incierta_no_se_considera_consumo_ni_aprobacion():
    cliente=ClienteFalso([{'stop_reason':'end_turn','content':[{'type':'text','text':'{}'}]} for _ in range(15)])
    cliente.presupuesto=CuentaPendiente()
    r=evaluar_experiencia(semilla(),cliente=cliente,clase_conversacion=ConversacionConReserva)
    assert r['completitud']['proporcion']==1
    assert r['operacion']['costo_total_usd']=='0'
    assert r['operacion']['reserva_pendiente_delta_usd']=='0.5'
    assert r['operacion']['cumple'] is False and r['cumple_automatico'] is False

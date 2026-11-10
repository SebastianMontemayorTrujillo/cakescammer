import json
from pathlib import Path

import pytest

from pasteles.configuracion import configuracion, entorno_hermes, guardar_telegram, leer_telegram


def test_perfil_restringe_herramientas_y_otros_proveedores() -> None:
    cfg = configuracion(Path('/proyecto'), '/python', Path('/datos'))
    assert cfg['platform_toolsets'] == {'cli': ['mcp-pasteles'], 'telegram': ['mcp-pasteles']}
    assert cfg['fallback_providers'] == []
    assert cfg['auth']['adopt_external_logins'] is False
    assert cfg['model']['streaming'] is False
    assert cfg['agent']['max_turns'] == 6
    assert cfg['mcp_servers']['pasteles']['cwd'] == '/proyecto'
    assert cfg['mcp_servers']['pasteles']['tools']['include'] == [
        'ver_catalogo', 'recomendar_pasteles', 'cotizar_pedido']
    assert cfg['gateway']['platforms']['telegram']['extra']['group_policy'] == 'disabled'
    assert cfg['gateway']['platforms']['telegram']['extra']['allow_admin_from'] == ['0']
    assert cfg['gateway']['standalone'] is True


def test_gateway_no_hereda_llaves_ni_configuracion_personal(monkeypatch) -> None:
    for clave in ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY',
                  'HERMES_HOME', 'PYTHONPATH', 'TELEGRAM_BOT_TOKEN', 'GATEWAY_ALLOWED_USERS']:
        monkeypatch.setenv(clave, 'valor-privado-de-prueba')
    entorno = entorno_hermes(raiz=Path('/proyecto'), datos=Path('/datos'), clave_local='local')
    assert 'valor-privado-de-prueba' not in json.dumps(entorno)
    assert entorno['PASTELES_PROXY_KEY'] == 'local'
    assert entorno['TELEGRAM_ALLOW_ALL_USERS'] == 'false'


def test_telegram_solo_un_usuario_y_archivo_privado(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_ALLOWED_USERS', raising=False)
    token = '123456:' + 'a' * 30
    guardar_telegram(tmp_path, token, '123456789')
    assert (tmp_path / '.env').stat().st_mode & 0o777 == 0o600
    assert leer_telegram(tmp_path)['TELEGRAM_ALLOWED_USERS'] == '123456789'
    with pytest.raises(ValueError):
        guardar_telegram(tmp_path, token, '*')
    with pytest.raises(ValueError):
        guardar_telegram(tmp_path, token + '\nOTRA=valor', '123456789')


def test_diagnostico_no_revela_secretos(monkeypatch) -> None:
    from pasteles.operacion import diagnostico
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secreto-no-imprimir')
    resultado = diagnostico()
    assert resultado['anthropic_en_entorno'] is True
    assert 'secreto-no-imprimir' not in json.dumps(resultado)


def test_no_permite_cambiar_la_cuenta_por_entorno(monkeypatch) -> None:
    from pasteles.configuracion import ruta_datos
    monkeypatch.setenv('PASTELES_DATOS', '/tmp/otra-cuenta')
    with pytest.raises(ValueError, match='cuenta'):
        ruta_datos()


def test_eval_y_gateway_excluyen_ejecucion_simultanea(tmp_path) -> None:
    from pasteles.operacion import bloqueo_exclusivo
    with bloqueo_exclusivo(tmp_path):
        with pytest.raises(ValueError, match='ejecución'):
            with bloqueo_exclusivo(tmp_path):
                pytest.fail('No debió obtener otro bloqueo.')
    with bloqueo_exclusivo(tmp_path):
        pass


def test_entorno_privado_preserva_telegram_y_rechaza_llave_anthropic(tmp_path) -> None:
    from pasteles.configuracion import guardar_entorno_perfil, leer_entorno_perfil
    guardar_telegram(tmp_path, '123456:' + 'a' * 30, '123456789')
    guardar_entorno_perfil(tmp_path, {'PASTELES_PROXY_KEY': 'b' * 40})
    valores = leer_entorno_perfil(tmp_path)
    assert valores['TELEGRAM_ALLOWED_USERS'] == '123456789'
    assert valores['PASTELES_PROXY_KEY'] == 'b' * 40
    with pytest.raises(ValueError):
        guardar_entorno_perfil(tmp_path, {'ANTHROPIC_API_KEY': 'no-persistir'})


def test_modo_publico_abre_solo_dm_y_obliga_consumidor_nativo(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secreto-de-prueba')
    monkeypatch.setenv('GATEWAY_ALLOW_ALL_USERS', 'true')
    cfg = configuracion(Path('/proyecto'), '/python', Path('/datos'), publico=True)
    extra = cfg['gateway']['platforms']['telegram']['extra']
    assert extra['dm_policy'] == 'open' and extra['group_policy'] == 'disabled'
    assert extra['allow_admin_from'] == ['0']
    entorno = entorno_hermes(raiz=Path('/proyecto'), datos=Path('/datos'), publico=True)
    assert entorno['TELEGRAM_ALLOW_ALL_USERS'] == 'true'
    assert entorno['TELEGRAM_DM_POLICY'] == 'open'
    assert entorno['PASTELES_PUBLICO'] == entorno['PASTELES_RSI'] == '1'
    assert entorno['GATEWAY_ALLOW_ALL_USERS'] == 'false'
    assert 'ANTHROPIC_API_KEY' not in entorno


def test_publico_persistente_y_reversible_conserva_credenciales(tmp_path, monkeypatch):
    from pasteles.configuracion import preparar_perfil, leer_entorno_perfil
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_ALLOWED_USERS', raising=False)
    perfil = tmp_path / 'perfil'
    opciones = dict(perfil=perfil, raiz=Path(__file__).resolve().parents[2],
                    datos=tmp_path / 'datos', crear_con_cli=False)
    preparar_perfil(**opciones, publico=True)
    token = '123456:' + 'a' * 30
    guardar_telegram(perfil, token, '123456789')
    anterior = leer_entorno_perfil(perfil)
    preparar_perfil(**opciones)
    assert leer_entorno_perfil(perfil) == anterior
    assert leer_telegram(perfil)['PASTELES_PUBLICO'] == '1'
    assert json.loads((perfil / 'config.yaml').read_text())['gateway']['platforms']['telegram']['extra']['dm_policy'] == 'open'
    preparar_perfil(**opciones, publico=False)
    assert leer_telegram(perfil)['PASTELES_PUBLICO'] == '0'
    assert leer_telegram(perfil)['TELEGRAM_BOT_TOKEN'] == token
    assert leer_entorno_perfil(perfil)['PASTELES_PROXY_KEY'] == anterior['PASTELES_PROXY_KEY']
    assert json.loads((perfil / 'config.yaml').read_text())['gateway']['platforms']['telegram']['extra']['dm_policy'] == 'allowlist'


def test_publico_no_necesita_lista_pero_si_token_y_flag_validos(tmp_path, monkeypatch):
    from pasteles.configuracion import guardar_entorno_perfil
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_ALLOWED_USERS', raising=False)
    guardar_entorno_perfil(tmp_path, {'PASTELES_PUBLICO': '1', 'TELEGRAM_BOT_TOKEN': '123456:' + 'a' * 30})
    assert leer_telegram(tmp_path)['PASTELES_PUBLICO'] == '1'
    guardar_entorno_perfil(tmp_path, {'PASTELES_PUBLICO': 'yes'})
    with pytest.raises(ValueError, match='PASTELES_PUBLICO'):
        leer_telegram(tmp_path)
    guardar_entorno_perfil(tmp_path, {'PASTELES_PUBLICO': '0'})
    with pytest.raises(ValueError, match='ID'):
        leer_telegram(tmp_path)
    guardar_entorno_perfil(tmp_path, {'PASTELES_PUBLICO': '1', 'TELEGRAM_BOT_TOKEN': ''})
    with pytest.raises(ValueError, match='token'):
        leer_telegram(tmp_path)

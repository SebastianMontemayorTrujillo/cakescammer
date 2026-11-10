# Telegram privado con Hermes

`python -m pasteles configurar` prepara un perfil exclusivo mediante
`hermes profile create pasteles --no-alias --no-skills`. No clona el perfil
personal. Se rehúsa a reemplazar perfiles ajenos. Su config.yaml es JSON
válido como YAML y no contiene la llave Anthropic.

`configurar --telegram` pide el token de un bot dedicado creado con /newbot
en BotFather y un único ID numérico. El token se introduce oculto y se guarda
en el .env del perfil con permisos 0600. Se bloquean grupos y usuarios ajenos.

`./INICIAR.sh` pide la llave Anthropic en memoria, inicia el proxy con cuenta
persistente y supervisa `hermes -p pasteles gateway run`. Su cwd es el workspace
del perfil; el MCP usa la raíz del proyecto independiente.

Antes de gastar, ejecutar `make humo` y `hermes -p pasteles mcp test pasteles`.
Para cargar el plugin al usar comandos administrativos manuales de Hermes,
definir PASTELES_RAIZ=/home/seb/pasteles y
PASTELES_DATOS=/home/seb/pasteles/.runtime. El launcher lo hace automáticamente.
El plugin usa plugins.isolation=in_process y el poller existente de Hermes.

Las tres herramientas MCP son de consulta. El plugin registra /pagar, /pedido
y callbacks exclusivos para pagos simulados. No hay pasarela real ni envío
al vendedor.

Referencias oficiales:
- [Proveedores](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
- [Plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- [Telegram](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)

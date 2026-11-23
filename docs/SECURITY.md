# Seguridad y privacidad

Jarvis puede leer y modificar archivos, interactuar con ventanas, acceder al
correo configurado y abrir páginas web. Ejecuta el programa solo en una cuenta
de usuario de confianza y revisa las confirmaciones antes de permitir acciones.

## Límites y confirmaciones

- Las herramientas de archivos limitan las rutas a `JARVIS_HOME_DIR`; conserva
  ese valor en `~` salvo que entiendas las consecuencias.
- Las herramientas sensibles pueden pedir confirmación mediante la GUI o el
  modo de texto. Sin callback de confirmación, la acción protegida se bloquea.
- Jarvis solo descubre aplicaciones gráficas registradas en archivos
  `.desktop` del menú del usuario/sistema; permite abrirlas, consultar si se
  ejecutan y cerrarlas, pero no interpreta texto del chat como comandos de
  terminal. `JARVIS_ALLOWED_APPS` solo mantiene compatibilidad con nombres
  antiguos que no tengan una entrada de menú. Al cerrar una aplicación
  Flatpak, la acción apunta a su identificador exacto.
- El acceso web está diseñado para URLs públicas HTTP/HTTPS; no debe usarse como
  frontera de seguridad para datos sensibles ni como proxy.
- El modelo local puede proponer acciones incorrectas. Las verificaciones y
  confirmaciones reducen riesgos, pero no sustituyen la supervisión humana.

## Datos enviados fuera del equipo

- El chat se envía al servidor Ollama configurado. Si Ollama está en otra
  máquina, el texto sale del equipo local.
- Las búsquedas envían la consulta al servicio de búsqueda web.
- Leer una URL descarga su contenido desde Internet.
- IMAP/SMTP envía credenciales y datos al proveedor configurado.
- Antes de cada petición a un Ollama remoto y de cada operación web, navegador
  o correo, Jarvis muestra el destino y los datos que enviará y solicita
  autorización. Una dirección de loopback (por ejemplo, `localhost`) no
  necesita ese consentimiento; los servidores de la red local sí.
- El análisis visual remoto muestra que se enviará una captura de pantalla
  completa y la instrucción indicada antes de enviar la imagen.
- Puedes cancelar una generación, escucha o respuesta hablada; una herramienta
  que ya empezó termina antes de detener los siguientes pasos.
- Los modelos de voz pueden descargarse durante la configuración inicial; la
  descarga no implica que el audio se envíe a un servicio remoto.

No envíes contraseñas, tokens ni datos privados en mensajes o prompts. Usa
credenciales dedicadas y guarda secretos solo en un `.env` excluido por Git.

## Reporte de problemas

No publiques logs, bases de datos, capturas de pantalla, `.env` ni volcados de
conversación sin revisar y eliminar previamente información personal.
Para reportar una vulnerabilidad, usa los canales privados de seguridad
disponibles en GitHub en lugar de abrir un issue público con detalles
explotables.

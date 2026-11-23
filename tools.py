"""Herramientas seguras y comprobables de Jarvis para Linux."""
import configparser
import logging
import os
import re
import shlex
import shutil
import subprocess
import webbrowser
import imaplib
import smtplib
import email as email_lib
import time
import socket
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
import requests
from core.browser_agent import BROWSER
from urllib.parse import urlparse
import ipaddress
import config, memory

logger=logging.getLogger(__name__)

class _DesktopEntryParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _resolve_executable(nombre):
    aliases={"librewolf":"librewolf", "calculadora":"gnome-calculator", "terminal":"gnome-terminal", "youtube":"xdg-open"}
    nombre=aliases.get((nombre or "").strip().lower(), (nombre or "").strip())
    exe=shutil.which(nombre)
    if exe: return exe
    home=os.path.expanduser("~")
    candidates=[os.path.join(home,".local","bin",nombre),os.path.join(home,".steam","debian-installation",nombre),os.path.join("/snap/bin",nombre),os.path.join("/usr/bin",nombre),os.path.join("/usr/local/bin",nombre)]
    if nombre=="steam": candidates=[os.path.join(home,".steam","debian-installation","steam.sh"),*candidates]
    return next((p for p in candidates if os.path.isfile(p) and os.access(p,os.X_OK)),None)

def _application_dirs():
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep)
    roots = [
        data_home / "applications",
        *(Path(path) / "applications" for path in data_dirs if path),
        Path("/var/lib/snapd/desktop/applications"),
        data_home / "flatpak" / "exports" / "share" / "applications",
        Path("/var/lib/flatpak/exports/share/applications"),
    ]
    seen = set()
    unique = []
    for path in roots:
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    return unique


def _read_desktop_entry(path, root):
    parser = _DesktopEntryParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
        entry = parser["Desktop Entry"]
    except (OSError, KeyError, configparser.Error, UnicodeError):
        return None

    if entry.get("Type", "Application") != "Application":
        return None
    try:
        if entry.getboolean("Hidden", fallback=False) or entry.getboolean("NoDisplay", fallback=False):
            return None
    except ValueError:
        logger.warning("Entrada .desktop con booleano inválido: %s", path)
        return None

    name = next(
        (entry[key] for key in ("Name[es_ES]", "Name[es]", "Name") if key in entry),
        "",
    ).strip()
    command = entry.get("Exec", "").strip()
    if not name or not command:
        return None
    try:
        exec_parts = shlex.split(command)
    except ValueError:
        return None
    if not exec_parts:
        return None

    executable = exec_parts[0]
    if executable == "env":
        executable = next(
            (part for part in exec_parts[1:] if not part.startswith("-") and "=" not in part),
            "",
        )
    flatpak_id = entry.get("X-Flatpak", "").strip()
    if Path(executable).name == "flatpak" and not flatpak_id:
        flatpak_id = next(
            (
                part for part in reversed(exec_parts)
                if re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", part)
            ),
            "",
        )
    try_exec = entry.get("TryExec", "").strip()
    if try_exec and not (shutil.which(try_exec) or Path(try_exec).is_file()):
        return None

    try:
        desktop_id = path.relative_to(root).as_posix().replace("/", "-")
    except ValueError:
        desktop_id = path.name
    return {
        "name": name,
        "id": desktop_id.removesuffix(".desktop"),
        "path": str(path),
        "exec": command,
        "executable": executable,
        "icon": entry.get("Icon", ""),
        "working_directory": entry.get("Path", ""),
        "terminal": entry.getboolean("Terminal", fallback=False),
        "flatpak_id": flatpak_id,
    }


def _installed_applications():
    applications = {}
    for root in _application_dirs():
        if not root.is_dir():
            continue
        try:
            paths = sorted(root.rglob("*.desktop"))
        except OSError:
            continue
        for path in paths:
            if path.is_symlink() and not path.exists():
                continue
            item = _read_desktop_entry(path, root)
            if item:
                applications.setdefault(item["id"].casefold(), item)
    return sorted(applications.values(), key=lambda item: item["name"].casefold())


def _normalise_app_name(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _find_application(name):
    query = (name or "").strip()
    if not query:
        raise ValueError("Debes indicar el nombre de una aplicación.")
    normalized = _normalise_app_name(query)
    applications = _installed_applications()
    exact = [
        app for app in applications
        if normalized in {
            _normalise_app_name(app["name"]),
            _normalise_app_name(app["id"]),
            _normalise_app_name(Path(app["executable"]).name),
            _normalise_app_name(app.get("flatpak_id", "")),
        }
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        names = ", ".join(app["name"] for app in exact[:5])
        raise ValueError(f"El nombre '{query}' coincide con varias aplicaciones: {names}.")

    matches = [
        app for app in applications
        if normalized and (
            normalized in _normalise_app_name(app["name"])
            or normalized in _normalise_app_name(app["id"])
            or normalized in _normalise_app_name(app.get("flatpak_id", ""))
        )
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(app["name"] for app in matches[:5])
        raise ValueError(f"El nombre '{query}' es ambiguo. Coincidencias: {names}.")
    legacy_name = next(
        (app for app in config.ALLOWED_APPS if _normalise_app_name(app) == normalized),
        None,
    )
    if legacy_name:
        executable = _resolve_executable(legacy_name)
        if executable:
            return {
                "name": legacy_name,
                "id": legacy_name,
                "path": "",
                "exec": shlex.quote(executable),
                "executable": executable,
                "icon": "",
                "working_directory": "",
                "terminal": False,
                "flatpak_id": "",
            }
    raise FileNotFoundError(
        f"No encontré '{query}' entre las aplicaciones gráficas instaladas. "
        "Pide listar_aplicaciones_permitidas para ver los nombres disponibles."
    )


def _desktop_exec_argv(application):
    try:
        parts = shlex.split(application["exec"])
    except ValueError as exc:
        raise ValueError(f"El lanzador de {application['name']} no es válido.") from exc

    argv = []
    field_codes = re.compile(r"%(?:[fFuUdDnNvm])")
    for part in parts:
        if part == "%i":
            if application["icon"]:
                argv.extend(("--icon", application["icon"]))
            continue
        if part in {"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m"}:
            continue
        part = part.replace("%%", "\0")
        part = part.replace("%c", application["name"]).replace("%k", application["path"])
        part = field_codes.sub("", part).replace("\0", "%")
        if part:
            argv.append(part)
    if not argv:
        raise ValueError(f"El lanzador de {application['name']} no contiene un comando.")
    return argv


def _launch_application(application):
    launcher = shutil.which("gtk-launch")
    if launcher:
        subprocess.Popen(
            [launcher, application["id"]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    argv = _desktop_exec_argv(application)
    working_directory = application["working_directory"]
    cwd = working_directory if working_directory and os.path.isdir(working_directory) else None
    if application["terminal"]:
        terminal = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal")
        if not terminal:
            raise RuntimeError(
                f"{application['name']} necesita un emulador de terminal y no hay ninguno instalado."
            )
        argv = [terminal, "-e", *argv]
    subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

def _validate_safe_path(path, must_exist=False):
    base=os.path.realpath(os.path.expanduser(config.HOME_DIR)); target=os.path.realpath(os.path.expanduser(path or base))
    if os.path.commonpath([base,target])!=base: raise ValueError(f"Ruta fuera del espacio permitido: {path}")
    if must_exist and not os.path.exists(target): raise FileNotFoundError(target)
    return target

def abrir_aplicacion(nombre):
    app = _find_application(nombre)
    _launch_application(app)
    return f"He iniciado {app['name']}."

def comprobar_aplicacion(nombre):
    app = _find_application(nombre)
    if app["flatpak_id"]:
        flatpak = shutil.which("flatpak")
        if not flatpak:
            return f"{app['name']} está instalada, pero no se encuentra el cliente Flatpak."
        try:
            result = subprocess.run(
                [flatpak, "ps", "--columns=application"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"No pude consultar el estado de {app['name']}: {exc}") from exc
        running = app["flatpak_id"] in {
            line.strip() for line in result.stdout.splitlines()
        }
        return f"{app['name']} está instalada y {'está ejecutándose' if running else 'no parece estar ejecutándose'}."

    executable = Path(app["executable"]).name
    try:
        running = subprocess.run(
            ["pgrep", "-x", executable],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        running = False
    return f"{app['name']} está instalada y {'está ejecutándose' if running else 'no parece estar ejecutándose'}."

def cerrar_aplicacion(nombre):
    app = _find_application(nombre)
    if app["executable"] and Path(app["executable"]).name == "flatpak":
        flatpak = shutil.which("flatpak")
        if not flatpak or not app["flatpak_id"]:
            raise RuntimeError(f"No pude identificar de forma segura la instancia Flatpak de {app['name']}.")
        try:
            result = subprocess.run(
                [flatpak, "kill", app["flatpak_id"]],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"No pude cerrar {app['name']}: {exc}") from exc
        if result.returncode:
            return f"{app['name']} no parece estar ejecutándose."
        return f"Solicitud de cierre enviada a {app['name']}."

    executable = Path(app["executable"]).name
    if not executable:
        raise RuntimeError(f"No pude identificar el proceso de {app['name']}.")
    try:
        result = subprocess.run(
            ["pkill", "-x", "-u", str(os.getuid()), executable],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"No pude cerrar {app['name']}: {exc}") from exc
    if result.returncode == 1:
        return f"{app['name']} no parece estar ejecutándose."
    if result.returncode != 0:
        raise RuntimeError(f"No pude cerrar {app['name']}: {result.stderr.strip()}")
    return f"Solicitud de cierre enviada a {app['name']}."

def listar_aplicaciones_permitidas(filtro=""):
    query = _normalise_app_name(filtro)
    installed = [
        app["name"] for app in _installed_applications()
        if not query or query in _normalise_app_name(app["name"]) or query in _normalise_app_name(app["id"])
    ]
    if not installed:
        return "No encontré aplicaciones gráficas instaladas que coincidan."
    shown = installed[:100]
    suffix = f"\nSe muestran las primeras 100 de {len(installed)}." if len(installed) > 100 else ""
    return "Aplicaciones gráficas instaladas: " + ", ".join(shown) + suffix

def _url_publica(url):
    parsed=urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host=parsed.hostname or ""
    if host.lower() in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        ip=ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        try:
            addresses=socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False
        if not addresses:
            return False
        for address in addresses:
            try:
                ip=ipaddress.ip_address(address[4][0])
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    return True

def buscar_en_web(consulta, cantidad=6):
    """Busca en la web y devuelve resultados estructurados con título, URL y fragmento."""
    consulta=(consulta or "").strip()
    if not consulta: raise ValueError("La consulta está vacía.")
    cantidad=max(1,min(int(cantidad),10))
    url="https://html.duckduckgo.com/html/"
    try:
        r=requests.get(url, params={"q":consulta}, headers={"User-Agent":"JarvisLocal/2.5"}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"No pude consultar el buscador: {exc}") from exc
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("Falta beautifulsoup4 para analizar resultados web.") from exc
    soup=BeautifulSoup(r.text,"html.parser")
    resultados=[]
    for item in soup.select(".result"):
        link=item.select_one("a.result__a")
        snippet=item.select_one(".result__snippet")
        if not link: continue
        href=link.get("href","")
        title=link.get_text(" ",strip=True)
        text=snippet.get_text(" ",strip=True) if snippet else ""
        if href and title:
            resultados.append({"titulo":title,"url":href,"fragmento":text})
        if len(resultados)>=cantidad: break
    if not resultados:
        return f"No encontré resultados claros para: {consulta}"
    lines=[f"Resultados para: {consulta}"]
    for i,item in enumerate(resultados,1):
        lines.append(f"{i}. {item['titulo']}\n   URL: {item['url']}\n   {item['fragmento']}")
    return "\n".join(lines)

def leer_pagina_web(url, max_chars=12000):
    """Descarga una página pública y extrae su texto principal para que el agente pueda analizarla."""
    url=(url or "").strip()
    if not _url_publica(url): raise ValueError("Solo se permiten URLs HTTP/HTTPS públicas.")
    max_chars=max(1000,min(int(max_chars),30000))
    try:
        r=requests.get(url, headers={"User-Agent":"JarvisLocal/2.5"}, timeout=15, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"No pude abrir la página: {exc}") from exc
    if not _url_publica(r.url): raise RuntimeError("La redirección apunta a una URL no permitida.")
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("Falta beautifulsoup4 para extraer el contenido web.") from exc
    soup=BeautifulSoup(r.text,"html.parser")
    for tag in soup(["script","style","noscript","svg","nav","footer"]): tag.decompose()
    title=soup.title.get_text(" ",strip=True) if soup.title else r.url
    main=soup.find("main") or soup.find("article") or soup.body or soup
    text=" ".join(main.stripped_strings)
    text=" ".join(text.split())
    return f"Título: {title}\nURL final: {r.url}\nContenido:\n{text[:max_chars]}"

def abrir_url(url):
    url=(url or "").strip()
    if not _url_publica(url): raise ValueError("Solo se permiten URLs HTTP/HTTPS públicas.")
    webbrowser.open(url)
    return f"He abierto: {url}"

def buscar_archivos(nombre,directorio=None):
    base=_validate_safe_path(directorio)
    if not nombre: raise ValueError("Debes indicar un nombre.")
    encontrados=[]
    for root,dirs,files in os.walk(base):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root,d))]
        for f in files:
            if nombre.lower() in f.lower(): encontrados.append(os.path.join(root,f))
            if len(encontrados)>=config.MAX_SEARCH_RESULTS: return "Encontré:\n"+"\n".join(encontrados)
    return "Encontré:\n"+"\n".join(encontrados) if encontrados else f"No encontré '{nombre}'."

def listar_archivos(directorio):
    safe=_validate_safe_path(directorio,True); items=os.listdir(safe)
    return "\n".join(sorted(items)) if items else f"'{safe}' está vacío."

def leer_archivo(ruta,max_chars=20000):
    p=_validate_safe_path(ruta,True)
    if not os.path.isfile(p): raise ValueError("La ruta no es un archivo.")
    with open(p,"r",encoding="utf-8",errors="replace") as f: return f.read(max_chars)

def crear_carpeta(ruta):
    p=_validate_safe_path(ruta); os.makedirs(p, exist_ok=False); return f"Carpeta creada: {p}"

def crear_archivo(ruta,contenido=""):
    p=_validate_safe_path(ruta); os.makedirs(os.path.dirname(p),exist_ok=True)
    if os.path.exists(p): raise FileExistsError(p)
    with open(p,"w",encoding="utf-8") as f: f.write(contenido)
    return f"Archivo creado: {p}"

def modificar_archivo(ruta,contenido):
    p=_validate_safe_path(ruta,True)
    if not os.path.isfile(p): raise ValueError("La ruta no es un archivo.")
    with open(p,"w",encoding="utf-8") as f: f.write(contenido)
    return f"Archivo modificado: {p}"

def eliminar_archivo(ruta):
    p=_validate_safe_path(ruta,True)
    if os.path.isdir(p): raise ValueError("No se permite eliminar directorios con esta herramienta.")
    os.remove(p); return f"Archivo eliminado: {p}"

def controlar_volumen(accion,nivel=None):
    if accion=="fijar":
        if nivel is None or not 0<=int(nivel)<=100: raise ValueError("El volumen debe estar entre 0 y 100.")
        subprocess.run(["amixer","-q","set","Master",f"{int(nivel)}%"],check=True); return f"Volumen fijado al {nivel}%"
    mapa={"subir":"10%+","bajar":"10%-","silenciar":"mute","activar":"unmute"}
    if accion not in mapa: raise ValueError(f"Acción de volumen no reconocida: {accion}")
    subprocess.run(["amixer","-q","set","Master",mapa[accion]],check=True); return f"Volumen: {accion}."

def controlar_musica(accion):
    mapa={"reproducir":"play","pausar":"pause","siguiente":"next","anterior":"previous","parar":"stop"}
    if accion not in mapa: raise ValueError(f"Acción de música no reconocida: {accion}")
    cmd=["playerctl"]+(["--player",config.MUSIC_PLAYER] if config.MUSIC_PLAYER else [])+[mapa[accion]]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE); return f"Música: {accion}."

def enviar_correo(destinatario,asunto,cuerpo):
    if not config.EMAIL_ADDRESS or not config.EMAIL_PASSWORD: raise RuntimeError("Correo no configurado.")
    msg=MIMEText(cuerpo); msg["Subject"]=asunto; msg["From"]=config.EMAIL_ADDRESS; msg["To"]=destinatario
    with smtplib.SMTP(config.SMTP_SERVER,config.SMTP_PORT,timeout=20) as server:
        server.starttls(); server.login(config.EMAIL_ADDRESS,config.EMAIL_PASSWORD); server.send_message(msg)
    return f"Correo enviado a {destinatario}."

def leer_correos(cantidad=5):
    if not config.EMAIL_ADDRESS or not config.EMAIL_PASSWORD: raise RuntimeError("Correo no configurado.")
    cantidad=max(1,min(int(cantidad),20)); imap=imaplib.IMAP4_SSL(config.IMAP_SERVER,config.IMAP_PORT); imap.login(config.EMAIL_ADDRESS,config.EMAIL_PASSWORD); imap.select("INBOX")
    try:
        status,data=imap.search(None,"UNSEEN")
        if status!="OK": raise RuntimeError("No pude consultar los correos.")
        ids=data[0].split()[-cantidad:]
        if not ids: return "No tienes correos sin leer."
        lines=[]
        for mid in reversed(ids):
            st,msg_data=imap.fetch(mid,"(RFC822)")
            if st!="OK":
                raise RuntimeError("No pude descargar uno de los correos sin leer.")
            raw = next(
                (
                    response[1]
                    for response in msg_data or []
                    if isinstance(response, tuple)
                    and len(response) > 1
                    and isinstance(response[1], bytes)
                ),
                None,
            )
            if raw is None:
                raise RuntimeError("El servidor devolvió un correo con formato inesperado.")
            msg=email_lib.message_from_bytes(raw)
            lines.append(f"- {msg.get('From','desconocido')} — {msg.get('Subject','(sin asunto)')}")
        return "Correos sin leer:\n"+"\n".join(lines)
    finally: imap.logout()



def navegador_abrir(url):
    return BROWSER.navigate(url)

def navegador_atras():
    return BROWSER.back()

def navegador_click_texto(texto):
    return BROWSER.click_text(texto)

def navegador_click_role(rol, nombre):
    return BROWSER.click_role(rol, nombre)

def navegador_escribir(campo, texto):
    return BROWSER.fill(campo, texto)

def navegador_tecla(tecla):
    return BROWSER.press(tecla)

def navegador_extraer(max_chars=12000):
    return BROWSER.extract(max_chars)

def navegador_estado():
    return BROWSER.status()

def navegador_cerrar():
    BROWSER.close()
    return "Navegador cerrado."

def obtener_fecha_hora(): return datetime.now().strftime("%A %d/%m/%Y, %H:%M:%S")

def uso_ram():
    with open("/proc/meminfo",encoding="utf-8") as f:
        vals = {
            key: int(value.split()[0])
            for key, value in (line.split(":", 1) for line in f if ":" in line)
        }
    total = vals.get("MemTotal", 0)
    if not total:
        raise RuntimeError("No pude determinar la memoria total del sistema.")
    available = vals.get("MemAvailable", 0)
    used = total - available
    pct = used / total * 100
    return f"RAM en uso: {used/1024/1024:.1f} GB ({pct:.1f}%)."

def estado_sistema():
    try:
        with open("/proc/meminfo",encoding="utf-8") as f: mem=f.read()
        vals={line.split(":",1)[0]:int(line.split(":",1)[1].split()[0]) for line in mem.splitlines() if ":" in line}; total=vals.get("MemTotal",0); avail=vals.get("MemAvailable",0); pct=((total-avail)/total*100 if total else 0)
    except Exception: total=avail=pct=0
    distro="desconocida"
    try:
        with open("/etc/os-release",encoding="utf-8") as f:
            info=dict(line.strip().split("=",1) for line in f if "=" in line)
        distro=info.get("PRETTY_NAME", distro).strip('"')
    except Exception: pass
    gpu="no detectada"
    try:
        r=subprocess.run(["nvidia-smi","--query-gpu=name","--format=csv,noheader"],capture_output=True,text=True,timeout=5)
        if r.returncode==0 and r.stdout.strip(): gpu=r.stdout.strip().splitlines()[0]
    except Exception: pass
    load=", ".join(f"{x:.2f}" for x in os.getloadavg()) if hasattr(os,"getloadavg") else "no disponible"; d=shutil.disk_usage("/")
    return f"Usuario: {os.getenv('USER','desconocido')}\nDistribución: {distro}\nKernel: {os.uname().sysname} {os.uname().release}\nGPU: {gpu}\nCarga: {load}\nRAM: {pct:.1f}% usada\nDisco: {d.used/(1024**3):.1f}/{d.total/(1024**3):.1f} GB (libre: {d.free/(1024**3):.1f} GB)"

def espacio_libre_disco():
    d=shutil.disk_usage("/")
    return f"Espacio libre en el disco principal: {d.free/(1024**3):.1f} GB."

def agendar_evento(titulo,fecha,hora="",descripcion=""): return memory.agendar_evento(titulo,fecha,hora,descripcion)
def listar_eventos(fecha: str | None = None): return memory.listar_eventos(fecha)

DISPATCH={"abrir_aplicacion":abrir_aplicacion, "crear_carpeta":crear_carpeta,"comprobar_aplicacion":comprobar_aplicacion,"cerrar_aplicacion":cerrar_aplicacion,"listar_aplicaciones_permitidas":listar_aplicaciones_permitidas,"buscar_en_web":buscar_en_web,"leer_pagina_web":leer_pagina_web,"abrir_url":abrir_url,"buscar_archivos":buscar_archivos,"listar_archivos":listar_archivos,"leer_archivo":leer_archivo,"crear_archivo":crear_archivo,"modificar_archivo":modificar_archivo,"eliminar_archivo":eliminar_archivo,"controlar_volumen":controlar_volumen,"controlar_musica":controlar_musica,"enviar_correo":enviar_correo,"leer_correos":leer_correos,"obtener_fecha_hora":obtener_fecha_hora,"estado_sistema":estado_sistema, "espacio_libre_disco":espacio_libre_disco, "uso_ram":uso_ram,"agendar_evento":agendar_evento,"listar_eventos":listar_eventos,"navegador_abrir":navegador_abrir,"navegador_atras":navegador_atras,"navegador_click_texto":navegador_click_texto,"navegador_click_role":navegador_click_role,"navegador_escribir":navegador_escribir,"navegador_tecla":navegador_tecla,"navegador_extraer":navegador_extraer,"navegador_estado":navegador_estado,"navegador_cerrar":navegador_cerrar}

def _schema(name,desc,props=None,required=None):
    return {"type":"function","function":{"name":name,"description":desc,"parameters":{"type":"object","properties":props or {},"required":required or []}}}
TOOL_SCHEMAS=[
 _schema("abrir_aplicacion","Abre cualquier aplicación gráfica instalada y visible en el menú del sistema.",{"nombre":{"type":"string"}},["nombre"]),
 _schema("comprobar_aplicacion","Comprueba si una aplicación está disponible y parece ejecutándose.",{"nombre":{"type":"string"}},["nombre"]),
 _schema("cerrar_aplicacion","Cierra una aplicación instalada del usuario actual; requiere confirmación.",{"nombre":{"type":"string"}},["nombre"]),
 _schema("listar_aplicaciones_permitidas","Lista las aplicaciones gráficas instaladas; admite un filtro opcional.",{"filtro":{"type":"string"}}),
 _schema("buscar_en_web","Busca en la web y devuelve varios resultados con título, URL y fragmento.",{"consulta":{"type":"string"},"cantidad":{"type":"integer"}},["consulta"]),
 _schema("leer_pagina_web","Descarga una página pública y extrae su texto para analizarla.",{"url":{"type":"string"},"max_chars":{"type":"integer"}},["url"]),
 _schema("abrir_url","Abre una URL pública en el navegador.",{"url":{"type":"string"}},["url"]),
 _schema("navegador_abrir","Abre una URL en el navegador automatizado de Jarvis.",{"url":{"type":"string"}},["url"]),
 _schema("navegador_atras","Vuelve a la página anterior del navegador automatizado."),
 _schema("navegador_click_texto","Hace clic en texto visible exacto dentro de la página web; requiere confirmación.",{"texto":{"type":"string"}},["texto"]),
 _schema("navegador_click_role","Hace clic en un elemento web por rol y nombre; requiere confirmación.",{"rol":{"type":"string"},"nombre":{"type":"string"}},["rol","nombre"]),
 _schema("navegador_escribir","Rellena un campo web por etiqueta o placeholder; requiere confirmación.",{"campo":{"type":"string"},"texto":{"type":"string"}},["campo","texto"]),
 _schema("navegador_tecla","Pulsa una tecla dentro de la página; requiere confirmación.",{"tecla":{"type":"string"}},["tecla"]),
 _schema("navegador_extraer","Extrae el texto visible de la página actual.",{"max_chars":{"type":"integer"}}),
 _schema("navegador_estado","Devuelve el estado y URL de la sesión del navegador."),
 _schema("navegador_cerrar","Cierra la sesión del navegador; requiere confirmación."),
 _schema("buscar_archivos","Busca archivos por nombre dentro del espacio permitido.",{"nombre":{"type":"string"},"directorio":{"type":"string"}},["nombre"]),
 _schema("listar_archivos","Lista un directorio permitido.",{"directorio":{"type":"string"}},["directorio"]),
 _schema("crear_carpeta","Crea una carpeta dentro del espacio permitido; requiere confirmación.",{"ruta":{"type":"string"}},["ruta"]),
 _schema("leer_archivo","Lee un archivo de texto permitido.",{"ruta":{"type":"string"}},["ruta"]),
 _schema("crear_archivo","Crea un archivo de texto; requiere confirmación.",{"ruta":{"type":"string"},"contenido":{"type":"string"}},["ruta"]),
 _schema("modificar_archivo","Reemplaza el contenido de un archivo; requiere confirmación.",{"ruta":{"type":"string"},"contenido":{"type":"string"}},["ruta","contenido"]),
 _schema("eliminar_archivo","Elimina un archivo, nunca un directorio; requiere confirmación.",{"ruta":{"type":"string"}},["ruta"]),
 _schema("controlar_volumen","Controla el volumen.",{"accion":{"type":"string"},"nivel":{"type":"integer"}},["accion"]),
 _schema("controlar_musica","Controla el reproductor MPRIS.",{"accion":{"type":"string"}},["accion"]),
 _schema("enviar_correo","Envía correo; requiere confirmación.",{"destinatario":{"type":"string"},"asunto":{"type":"string"},"cuerpo":{"type":"string"}},["destinatario","asunto","cuerpo"]),
 _schema("leer_correos","Lee asuntos/remitentes de correos no leídos.",{"cantidad":{"type":"integer"}}),
 _schema("obtener_fecha_hora","Obtiene fecha y hora local."),
 _schema("estado_sistema","Obtiene estado básico del sistema."),
 _schema("agendar_evento","Crea un evento local.",{"titulo":{"type":"string"},"fecha":{"type":"string"},"hora":{"type":"string"},"descripcion":{"type":"string"}},["titulo","fecha"]),
 _schema("uso_ram","Devuelve solo el uso actual de RAM, sin información adicional."),
 _schema("espacio_libre_disco","Devuelve el espacio libre del disco principal."),
 _schema("listar_eventos","Lista eventos locales.",{"fecha":{"type":"string"}}),
]

# --- Control de procesos (solo procesos del usuario actual) -----------------
def listar_procesos(filtro: str = "", limite: int = 20):
    """Lista procesos del usuario actual; opcionalmente filtra por nombre."""
    import getpass
    filtro = (filtro or "").strip().lower()
    limite = max(1, min(int(limite), 50))
    user = getpass.getuser()
    try:
        out = subprocess.check_output(["ps", "-u", user, "-o", "pid=,comm=,%cpu=,%mem=", "--sort=-%cpu"], text=True, timeout=5)
    except Exception as exc:
        raise RuntimeError(f"No pude consultar procesos: {exc}") from exc
    rows=[]
    for line in out.splitlines():
        parts=line.split()
        if len(parts) < 4: continue
        if filtro and filtro not in parts[1].lower(): continue
        rows.append(f"PID {parts[0]} | {parts[1]} | CPU {parts[2]}% | RAM {parts[3]}%")
        if len(rows)>=limite: break
    return "\n".join(rows) if rows else "No encontré procesos que coincidan."


def obtener_proceso(nombre: str):
    """Devuelve PIDs del usuario actual que coinciden exactamente con el nombre."""
    import getpass
    nombre=(nombre or "").strip()
    if not nombre: raise ValueError("Debes indicar el nombre del proceso.")
    user=getpass.getuser()
    try:
        out=subprocess.check_output(["pgrep","-u",user,"-x",nombre], text=True, stderr=subprocess.DEVNULL, timeout=5)
    except subprocess.CalledProcessError:
        return f"El proceso '{nombre}' no está ejecutándose para el usuario actual."
    pids=[x.strip() for x in out.splitlines() if x.strip()]
    return f"'{nombre}' está ejecutándose. PID(s): {', '.join(pids)}"


# Extend dispatch and schemas without duplicating the original list.
DISPATCH.update({"listar_procesos": listar_procesos, "obtener_proceso": obtener_proceso})
TOOL_SCHEMAS.extend([
    _schema("listar_procesos", "Lista procesos del usuario actual, opcionalmente filtrados.", {"filtro":{"type":"string"},"limite":{"type":"integer"}}),
    _schema("obtener_proceso", "Comprueba si un proceso exacto del usuario actual está ejecutándose.", {"nombre":{"type":"string"}}, ["nombre"]),
])

# ---------------------------------------------------------------------------
# Memoria y productividad
# ---------------------------------------------------------------------------
def guardar_recuerdo(clave, valor, categoria="general"):
    return memory.guardar_recuerdo(clave, valor, categoria)

def buscar_recuerdos(consulta="", categoria=""):
    return memory.buscar_recuerdos(consulta, categoria)

def borrar_recuerdo(clave):
    return memory.borrar_recuerdo(clave)

def crear_recordatorio(texto, cuando):
    return memory.crear_recordatorio(texto, cuando)

def listar_recordatorios(incluir_completados=False):
    return memory.listar_recordatorios(incluir_completados)

def completar_recordatorio(recordatorio_id):
    return memory.completar_recordatorio(recordatorio_id)


# ---------------------------------------------------------------------------
# Control de ventanas (opcional: requiere wmctrl)
# ---------------------------------------------------------------------------
def _wmctrl_available():
    return shutil.which("wmctrl") is not None

def listar_ventanas():
    if not _wmctrl_available():
        return "El control de ventanas requiere 'wmctrl'."
    try:
        out = subprocess.check_output(["wmctrl", "-l", "-p"], text=True, timeout=5)
    except Exception as exc:
        raise RuntimeError(f"No pude consultar ventanas: {exc}") from exc
    rows=[]
    for line in out.splitlines():
        parts=line.split(None, 4)
        if len(parts) >= 5:
            rows.append(f"ID {parts[0]} | PID {parts[2]} | {parts[4]}")
    return "Ventanas abiertas:\n" + "\n".join(rows) if rows else "No encontré ventanas abiertas."

def enfocar_ventana(titulo):
    if not _wmctrl_available():
        raise RuntimeError("El control de ventanas requiere 'wmctrl'.")
    titulo=(titulo or "").strip()
    if not titulo: raise ValueError("Debes indicar parte del título de la ventana.")
    subprocess.run(["wmctrl", "-a", titulo], check=True, timeout=5)
    return f"Ventana enfocada: {titulo}"


def mover_redimensionar_ventana(titulo, x, y, ancho, alto):
    if not _wmctrl_available():
        raise RuntimeError("El control de ventanas requiere 'wmctrl'.")
    titulo=(titulo or "").strip()
    x,y,ancho,alto=map(int,(x,y,ancho,alto))
    if not titulo or ancho < 100 or alto < 80:
        raise ValueError("Título y dimensiones de ventana no válidos.")
    if not 0 <= x <= 10000 or not 0 <= y <= 10000 or ancho > 10000 or alto > 10000:
        raise ValueError("Posición o tamaño fuera de límites razonables.")
    subprocess.run(["wmctrl","-r",titulo,"-e",f"0,{x},{y},{ancho},{alto}"],check=True,timeout=5)
    return f"Ventana '{titulo}' colocada en ({x},{y}) con tamaño {ancho}x{alto}."




def crear_tarea(titulo, descripcion="", prioridad=2, vence=""):
    return memory.crear_tarea(titulo, descripcion, prioridad, vence)

def listar_tareas(estado="pendiente"):
    return memory.listar_tareas(estado)

def actualizar_tarea(tarea_id, estado="", prioridad=0, titulo="", descripcion="", vence=""):
    return memory.actualizar_tarea(tarea_id, estado, prioridad, titulo, descripcion, vence)

def completar_tarea(tarea_id):
    return memory.completar_tarea(tarea_id)

def cancelar_tarea(tarea_id):
    return memory.cancelar_tarea(tarea_id)

def obtener_contexto_relevante(consulta, max_recuerdos=8, max_tareas=8):
    return memory.contexto_relevante(consulta, max_recuerdos, max_tareas)

DISPATCH.update({
    "guardar_recuerdo": guardar_recuerdo,
    "buscar_recuerdos": buscar_recuerdos,
    "borrar_recuerdo": borrar_recuerdo,
    "crear_recordatorio": crear_recordatorio,
    "listar_recordatorios": listar_recordatorios,
    "completar_recordatorio": completar_recordatorio,
    "listar_ventanas": listar_ventanas,
    "enfocar_ventana": enfocar_ventana,
    "mover_redimensionar_ventana": mover_redimensionar_ventana,
    "crear_tarea": crear_tarea,
    "listar_tareas": listar_tareas,
    "actualizar_tarea": actualizar_tarea,
    "completar_tarea": completar_tarea,
    "cancelar_tarea": cancelar_tarea,
    "obtener_contexto_relevante": obtener_contexto_relevante,
})
TOOL_SCHEMAS.extend([
    _schema("guardar_recuerdo", "Guarda una preferencia o dato explícitamente indicado por el usuario para futuras conversaciones.", {"clave":{"type":"string"},"valor":{"type":"string"},"categoria":{"type":"string"}}, ["clave","valor"]),
    _schema("buscar_recuerdos", "Busca información previamente guardada en la memoria local.", {"consulta":{"type":"string"},"categoria":{"type":"string"}}),
    _schema("borrar_recuerdo", "Elimina un recuerdo concreto; requiere confirmación.", {"clave":{"type":"string"}}, ["clave"]),
    _schema("crear_recordatorio", "Crea un recordatorio local. La fecha/hora se guarda como texto y no ejecuta comandos del sistema.", {"texto":{"type":"string"},"cuando":{"type":"string"}}, ["texto","cuando"]),
    _schema("listar_recordatorios", "Lista recordatorios locales pendientes.", {"incluir_completados":{"type":"boolean"}}),
    _schema("completar_recordatorio", "Marca un recordatorio local como completado.", {"recordatorio_id":{"type":"integer"}}, ["recordatorio_id"]),
    _schema("listar_ventanas", "Lista ventanas abiertas mediante wmctrl si está instalado."),
    _schema("enfocar_ventana", "Enfoca una ventana cuyo título contenga el texto indicado.", {"titulo":{"type":"string"}}, ["titulo"]),
    _schema("mover_redimensionar_ventana", "Mueve y redimensiona una ventana por título; requiere wmctrl.", {"titulo":{"type":"string"},"x":{"type":"integer"},"y":{"type":"integer"},"ancho":{"type":"integer"},"alto":{"type":"integer"}}, ["titulo","x","y","ancho","alto"]),
    _schema("crear_tarea", "Crea una tarea persistente local. No ejecuta acciones del sistema.", {"titulo":{"type":"string"},"descripcion":{"type":"string"},"prioridad":{"type":"integer","minimum":1,"maximum":3},"vence":{"type":"string"}}, ["titulo"]),
    _schema("listar_tareas", "Lista tareas persistentes por estado.", {"estado":{"type":"string","enum":["pendiente","en_progreso","completada","cancelada","todas"]}}),
    _schema("actualizar_tarea", "Actualiza una tarea persistente.", {"tarea_id":{"type":"integer"},"estado":{"type":"string"},"prioridad":{"type":"integer"},"titulo":{"type":"string"},"descripcion":{"type":"string"},"vence":{"type":"string"}}, ["tarea_id"]),
    _schema("completar_tarea", "Marca una tarea persistente como completada.", {"tarea_id":{"type":"integer"}}, ["tarea_id"]),
    _schema("cancelar_tarea", "Cancela una tarea persistente.", {"tarea_id":{"type":"integer"}}, ["tarea_id"]),
    _schema("obtener_contexto_relevante", "Consulta contexto persistente relevante para una petición sin modificar la memoria.", {"consulta":{"type":"string"},"max_recuerdos":{"type":"integer"},"max_tareas":{"type":"integer"}} , ["consulta"]),
])


# ---------------------------------------------------------------------------
# Visión básica del escritorio: captura + OCR (requiere mss, Pillow y tesseract)
# ---------------------------------------------------------------------------
def _ocr_dependencies():
    try:
        import mss
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("Faltan dependencias de visión: instala mss, Pillow y pytesseract con requirements.txt.") from exc
    if shutil.which("tesseract") is None:
        raise RuntimeError("Falta Tesseract OCR. Instálalo con: sudo apt install tesseract-ocr")
    return mss, Image, pytesseract

def capturar_pantalla():
    out_dir=os.path.join(str(config.DATA_DIR),"screenshots"); os.makedirs(out_dir,exist_ok=True)
    path=os.path.join(out_dir,time.strftime("screenshot_%Y%m%d_%H%M%S.png"))
    cmd=None
    if shutil.which("gnome-screenshot"): cmd=["gnome-screenshot","-f",path]
    elif shutil.which("scrot"): cmd=["scrot",path]
    elif shutil.which("import"): cmd=["import","-window","root",path]
    else: raise RuntimeError("No hay una herramienta de captura instalada.")
    subprocess.run(cmd,check=True,timeout=15)
    if not os.path.isfile(path) or os.path.getsize(path)==0: raise RuntimeError("La captura no se creó correctamente.")
    return {"path":path,"size":os.path.getsize(path)}


def observar_pantalla(max_chars=12000, incluir_invisibles=False):
    """Captura la pantalla y devuelve el texto OCR con coordenadas de cada bloque.
    El agente puede usar estas coordenadas para decidir dónde interactuar.
    """
    mss, Image, pytesseract = _ocr_dependencies()
    max_chars=max(1000,min(int(max_chars),30000))
    try:
        with mss.mss() as grabber:
            monitor=grabber.monitors[0]
            shot=grabber.grab(monitor)
            image=Image.frombytes("RGB", shot.size, shot.rgb)
            data=pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config="--psm 11")
    except Exception as exc:
        raise RuntimeError(f"No pude capturar/OCR de la pantalla: {exc}") from exc

    tokens=[]
    n=len(data.get("text", []))
    for i in range(n):
        text=(data["text"][i] or "").strip()
        try:
            conf=float(data["conf"][i])
        except (TypeError,ValueError):
            conf=-1
        if not text or (conf < 25 and not incluir_invisibles):
            continue
        try:
            left=int(data["left"][i]); top=int(data["top"][i])
            width=int(data["width"][i]); height=int(data["height"][i])
        except (TypeError,ValueError):
            continue
        tokens.append({"texto":text,"confianza":round(conf,1),"x":left,"y":top,"ancho":width,"alto":height})

    if not tokens:
        return f"Pantalla capturada ({shot.width}x{shot.height}), pero no se detectó texto legible."

    lines=[f"Pantalla: {shot.width}x{shot.height}", "Texto detectado (coordenadas del centro):"]
    for item in tokens:
        cx=item["x"] + item["ancho"]//2
        cy=item["y"] + item["alto"]//2
        lines.append(f'- "{item["texto"]}" @ ({cx},{cy}) confianza={item["confianza"]}%')
    result="\n".join(lines)
    return result[:max_chars]

def hacer_click_en_texto(texto, boton=1):
    """Busca texto visible mediante OCR y hace click en su centro.
    Requiere confirmación porque interactúa con la interfaz gráfica.
    """
    objetivo=(texto or "").strip().lower()
    if not objetivo:
        raise ValueError("Debes indicar el texto que quieres pulsar.")
    mss, Image, pytesseract = _ocr_dependencies()
    boton=int(boton)
    if boton not in (1,2,3):
        raise ValueError("El botón debe ser 1, 2 o 3.")
    try:
        with mss.mss() as grabber:
            monitor=grabber.monitors[0]
            shot=grabber.grab(monitor)
            image=Image.frombytes("RGB", shot.size, shot.rgb)
            data=pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config="--psm 11")
    except Exception as exc:
        raise RuntimeError(f"No pude analizar la pantalla: {exc}") from exc

    n=len(data.get("text", []))
    candidatos=[]
    for i in range(n):
        text=(data["text"][i] or "").strip()
        if not text or objetivo not in text.lower():
            continue
        try:
            conf=float(data["conf"][i]); x=int(data["left"][i]); y=int(data["top"][i]); w=int(data["width"][i]); h=int(data["height"][i])
        except (TypeError,ValueError):
            continue
        if conf >= 25:
            candidatos.append((conf,text,x,y,w,h))
    if not candidatos:
        raise FileNotFoundError(f"No encontré texto visible que coincida con '{texto}'.")
    candidatos.sort(reverse=True)
    conf,text,x,y,w,h=candidatos[0]
    cx=x+w//2; cy=y+h//2
    _require_xdotool()
    subprocess.run(["xdotool","mousemove","--sync",str(cx),str(cy)],check=True,timeout=5)
    subprocess.run(["xdotool","click",str(boton)],check=True,timeout=5)
    return f"He pulsado '{text}' en ({cx},{cy}), confianza OCR {conf:.1f}%."

DISPATCH.update({
    "capturar_pantalla":capturar_pantalla, "observar_pantalla":observar_pantalla,
    "hacer_click_en_texto":hacer_click_en_texto,
})
TOOL_SCHEMAS.extend([
    _schema("capturar_pantalla","Captura la pantalla sin OCR."),
    _schema("observar_pantalla","Captura la pantalla y usa OCR para detectar texto visible con coordenadas; sirve para observar la interfaz.",{"max_chars":{"type":"integer"}}),
    _schema("hacer_click_en_texto","Busca un texto visible mediante OCR y hace click en su centro; requiere confirmación.",{"texto":{"type":"string"},"boton":{"type":"integer"}},["texto"]),
])

# ---------------------------------------------------------------------------
# Control de escritorio real (opcional: requiere xdotool)
# ---------------------------------------------------------------------------
def _xdotool_available():
    return shutil.which("xdotool") is not None

def _require_xdotool():
    if not _xdotool_available():
        raise RuntimeError("El control de escritorio requiere 'xdotool'. Instálalo con: sudo apt install xdotool")

def obtener_posicion_raton():
    _require_xdotool()
    out=subprocess.check_output(["xdotool","getmouselocation","--shell"],text=True,timeout=5)
    vals={}
    for line in out.splitlines():
        if "=" in line:
            k,v=line.split("=",1); vals[k]=v
    return f"Ratón: x={vals.get('X','?')}, y={vals.get('Y','?')}, pantalla={vals.get('SCREEN','?')}"

def obtener_tamano_pantalla():
    _require_xdotool()
    out=subprocess.check_output(["xdotool","getdisplaygeometry"],text=True,timeout=5).strip()
    return f"Pantalla: {out}"

def mover_raton(x,y):
    _require_xdotool(); x,y=int(x),int(y)
    if not (0<=x<=10000 and 0<=y<=10000): raise ValueError("Coordenadas fuera de límites razonables.")
    subprocess.run(["xdotool","mousemove","--sync",str(x),str(y)],check=True,timeout=5)
    return f"Ratón movido a ({x},{y})."

def hacer_click(x=None,y=None,boton=1):
    _require_xdotool(); boton=int(boton)
    if boton not in (1,2,3): raise ValueError("El botón debe ser 1, 2 o 3.")
    if x is not None or y is not None:
        if x is None or y is None: raise ValueError("Debes indicar x e y juntas.")
        x,y=int(x),int(y)
        if not (0<=x<=10000 and 0<=y<=10000): raise ValueError("Coordenadas fuera de límites razonables.")
        subprocess.run(["xdotool","mousemove","--sync",str(x),str(y)],check=True,timeout=5)
    subprocess.run(["xdotool","click",str(boton)],check=True,timeout=5)
    return f"Click realizado con botón {boton}."

def escribir_en_escritorio(texto,intervalo=0):
    _require_xdotool(); texto=str(texto or "")
    if not texto: raise ValueError("El texto está vacío.")
    if len(texto)>5000: raise ValueError("Texto demasiado largo para una sola acción.")
    intervalo=max(0,min(int(intervalo),200))
    subprocess.run(["xdotool","type","--clearmodifiers","--delay",str(intervalo),texto],check=True,timeout=15)
    return "Texto escrito en la ventana activa."

def pulsar_tecla(teclas):
    _require_xdotool(); teclas=(teclas or "").strip()
    if not teclas or len(teclas)>80: raise ValueError("Combinación de teclas no válida.")
    import re
    if not re.fullmatch(r"[A-Za-z0-9_+:-]+",teclas): raise ValueError("La combinación contiene caracteres no permitidos.")
    subprocess.run(["xdotool","key","--clearmodifiers",teclas],check=True,timeout=5)
    return f"Tecla/combinación enviada: {teclas}"

DISPATCH.update({
    "obtener_posicion_raton":obtener_posicion_raton,
    "obtener_tamano_pantalla":obtener_tamano_pantalla,
    "mover_raton":mover_raton,
    "hacer_click":hacer_click,
    "escribir_en_escritorio":escribir_en_escritorio,
    "pulsar_tecla":pulsar_tecla,
})
TOOL_SCHEMAS.extend([
    _schema("obtener_posicion_raton","Obtiene la posición actual del cursor mediante xdotool."),
    _schema("obtener_tamano_pantalla","Obtiene la resolución de la pantalla mediante xdotool."),
    _schema("mover_raton","Mueve el cursor a unas coordenadas de pantalla.",{"x":{"type":"integer"},"y":{"type":"integer"}},["x","y"]),
    _schema("hacer_click","Hace un click en la posición indicada o en la posición actual; requiere confirmación.",{"x":{"type":"integer"},"y":{"type":"integer"},"boton":{"type":"integer"}}),
    _schema("escribir_en_escritorio","Escribe texto en la ventana activa; requiere confirmación.",{"texto":{"type":"string"},"intervalo":{"type":"integer"}},["texto"]),
    _schema("pulsar_tecla","Envía una tecla o combinación como ctrl+l, alt+F4 o Return; requiere confirmación.",{"teclas":{"type":"string"}},["teclas"]),
])

# ---------------------------------------------------------------------------
# Visión avanzada del escritorio
# ---------------------------------------------------------------------------
def analizar_pantalla(max_elementos=150, incluir_vision=True, prompt=""):
    from core.vision import VISION
    result = VISION.inspect(
        max_elements=max(1, min(int(max_elementos), 500)),
        include_visual=bool(incluir_vision),
        prompt=(prompt or "").strip() or None,
    )
    return result


def buscar_elemento_visual(texto, exacto=False):
    from core.vision import VISION
    image = VISION._capture()
    elements = VISION.ocr(image=image)
    matches = VISION.find(elements, texto, exact=bool(exacto))
    return {
        "query": texto,
        "exact": bool(exacto),
        "matches": [e.to_dict() for e in matches[:20]],
        "count": len(matches),
        "screen_size": [image.width, image.height],
    }


def esperar_elemento_visual(texto, timeout=10, intervalo=0.5):
    from core.vision import VISION
    started = time.monotonic()
    limit = max(0.5, min(float(timeout), 60.0))
    deadline = started + limit
    while time.monotonic() < deadline:
        image = VISION._capture()
        matches = VISION.find(VISION.ocr(image=image), texto)
        if matches:
            return {"found": True, "element": matches[0].to_dict(), "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}
        time.sleep(max(0.1, min(float(intervalo), 2.0)))
    return {"found": False, "texto": texto, "timeout_seconds": limit, "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}


def click_elemento_visual(texto, boton=1, exacto=False):
    from core.vision import VISION
    matches = buscar_elemento_visual(texto, exacto=exacto)["matches"]
    if not matches:
        raise FileNotFoundError(f"No encontré el elemento visual '{texto}'.")
    element = matches[0]
    x, y = element["center"]
    _require_xdotool()
    boton = int(boton)
    if boton not in (1, 2, 3):
        raise ValueError("El botón debe ser 1, 2 o 3.")
    subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], check=True, timeout=5)
    subprocess.run(["xdotool", "click", str(boton)], check=True, timeout=5)
    return {"clicked": element, "button": boton}


DISPATCH.update({
    "analizar_pantalla": analizar_pantalla,
    "buscar_elemento_visual": buscar_elemento_visual,
    "esperar_elemento_visual": esperar_elemento_visual,
    "click_elemento_visual": click_elemento_visual,
})
TOOL_SCHEMAS.extend([
    _schema("analizar_pantalla", "Analiza la pantalla con OCR y, si el modelo lo admite, con visión multimodal local; devuelve elementos y descripción visual.", {
        "max_elementos": {"type": "integer"},
        "incluir_vision": {"type": "boolean"},
        "prompt": {"type": "string"},
    }),
    _schema("buscar_elemento_visual", "Busca un texto visible en la pantalla y devuelve sus coordenadas.", {
        "texto": {"type": "string"},
        "exacto": {"type": "boolean"},
    }, ["texto"]),
    _schema("esperar_elemento_visual", "Espera hasta que un texto aparezca en la pantalla.", {
        "texto": {"type": "string"},
        "timeout": {"type": "number"},
        "intervalo": {"type": "number"},
    }, ["texto"]),
    _schema("click_elemento_visual", "Busca un elemento visible por texto y hace click en su centro; requiere confirmación.", {
        "texto": {"type": "string"},
        "boton": {"type": "integer"},
        "exacto": {"type": "boolean"},
    }, ["texto"]),
])

TOOL_GROUPS = {
    "web": {
        "buscar_en_web", "leer_pagina_web", "abrir_url",
    },
    "browser": {
        "navegador_abrir", "navegador_atras", "navegador_click_texto",
        "navegador_click_role", "navegador_escribir", "navegador_tecla",
        "navegador_extraer", "navegador_estado", "navegador_cerrar",
    },
    "desktop": {
        "obtener_fecha_hora", "estado_sistema", "espacio_libre_disco", "uso_ram",
        "listar_procesos", "obtener_proceso", "listar_ventanas", "enfocar_ventana",
        "mover_redimensionar_ventana", "capturar_pantalla", "observar_pantalla",
        "hacer_click_en_texto", "obtener_posicion_raton", "obtener_tamano_pantalla",
        "mover_raton", "hacer_click", "escribir_en_escritorio", "pulsar_tecla",
        "analizar_pantalla", "buscar_elemento_visual", "esperar_elemento_visual",
        "click_elemento_visual",
    },
    "files": {
        "buscar_archivos", "listar_archivos", "leer_archivo", "crear_archivo",
        "modificar_archivo", "eliminar_archivo", "crear_carpeta",
    },
    "email": {"leer_correos", "enviar_correo"},
    "media": {
        "abrir_aplicacion", "comprobar_aplicacion", "cerrar_aplicacion",
        "listar_aplicaciones_permitidas", "controlar_volumen", "controlar_musica",
    },
    "memory": {
        "agendar_evento", "listar_eventos", "guardar_recuerdo", "buscar_recuerdos",
        "borrar_recuerdo", "crear_recordatorio", "listar_recordatorios",
        "completar_recordatorio", "crear_tarea", "listar_tareas", "actualizar_tarea",
        "completar_tarea", "cancelar_tarea", "obtener_contexto_relevante",
    },
}

TOOL_GROUP_LABELS = {
    "web": "Búsqueda y lectura web",
    "browser": "Automatización del navegador",
    "desktop": "Sistema y control de escritorio",
    "files": "Archivos",
    "email": "Correo",
    "media": "Aplicaciones y medios",
    "memory": "Memoria y productividad",
}

TOOL_TO_GROUP = {
    name: group for group, names in TOOL_GROUPS.items() for name in names
}

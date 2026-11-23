"""Enrutador determinista para acciones comunes.

Evita que el LLM pueda simular acciones sencillas: si una petición coincide con
una intención de control conocida, se ejecuta directamente mediante ToolManager.
"""
from __future__ import annotations
import ast, operator, re
from typing import Optional

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}

def _calc(node):
    if isinstance(node, ast.Expression): return _calc(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int,float)) and not isinstance(node.value,bool): return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN: return _UN[type(node.op)](_calc(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a,b=_calc(node.left),_calc(node.right)
        if isinstance(node.op, ast.Pow) and abs(b)>20: raise ValueError("Exponente demasiado grande.")
        return _BIN[type(node.op)](a,b)
    raise ValueError("Expresión no permitida.")

def _calculator(text):
    m=re.search(r'(?:calcula|calcular|cu[aá]nto es|resuelve)\s+([0-9][0-9\s+\-*/%().,^×÷]+)', text.lower())
    if not m: return None
    expr=m.group(1).replace('×','*').replace('÷','/').replace('^','**').strip()
    try:
        value=_calc(ast.parse(expr, mode="eval"))
        if isinstance(value,float) and value.is_integer(): value=int(value)
        return f"El resultado es {value}."
    except Exception: return None

def _run(manager,name,args):
    result=manager.execute(name,args)
    call_id=f"router-{manager.last_run.get('tool_call_count', 0)+1}"
    record={"call_id":call_id,"tool":name,"arguments":args,"result":result.to_dict()}
    manager.last_run.setdefault("tool_calls",[]).append({"call_id":call_id,"tool":name,"arguments":args})
    manager.last_run.setdefault("tool_results",[]).append(record)
    manager.last_run["tool_call_count"]=manager.last_run.get("tool_call_count",0)+1
    return result.message if result.success else f"No pude completar la acción: {result.error or result.message}"

def route(text: str, manager) -> Optional[str]:
    t=(text or '').strip(); low=t.lower()
    # Fecha/hora
    if re.search(r'\b(hora|fecha y hora|fecha actual|fecha de hoy)\b', low) and not re.search(r'\b(hora|fecha)\s+de\s+(una|un)\b', low):
        return _run(manager,'obtener_fecha_hora',{})
    # Abrir URL/web concreta
    m=re.search(r'\b(?:abre|abrir|abreme|abrirme)\s+(https?://\S+)',t,re.I)
    if m: return _run(manager,'abrir_url',{'url':m.group(1).rstrip('.,')})
    if re.search(r'\b(?:abre|abrir)\s+(?:youtube|google|gmail)\b',low):
        site={'youtube':'https://www.youtube.com','google':'https://www.google.com','gmail':'https://mail.google.com'}
        key=next(k for k in site if k in low); return _run(manager,'abrir_url',{'url':site[key]})
    # Aplicaciones
    m=re.search(r'\b(?:abre|abrir|inicia|iniciar|ejecuta|ejecutar)\s+(?:(?:otra vez|de nuevo)\s+)?(?:la\s+)?(.+?)(?:\s+por favor)?$',t,re.I)
    if m:
        app=m.group(1).strip(' ."\'')
        aliases={'calculadora':'gnome-calculator','terminal':'gnome-terminal','librewolf':'librewolf','steam':'steam','brave':'brave','chrome':'chrome','chromium':'chromium','code':'code','discord':'discord','vlc':'vlc'}
        key=app.lower()
        if key in aliases: return _run(manager,'abrir_aplicacion',{'nombre':aliases[key]})
    m=re.search(r'\b(?:cierra|cerrar|cierra la|cerrar la)\s+(.+?)\s*$',t,re.I)
    if m:
        app=m.group(1).strip(' ."\''); aliases={'calculadora':'gnome-calculator','terminal':'gnome-terminal','librewolf':'librewolf','steam':'steam','brave':'brave','chrome':'chrome','chromium':'chromium','code':'code','discord':'discord','vlc':'vlc'}
        if app.lower() in aliases: return _run(manager,'cerrar_aplicacion',{'nombre':aliases[app.lower()]})
    # Sistema/procesos/ventanas/archivos
    if re.search(r'\b(aplicaciones?|procesos?)\b',low) and re.search(r'\b(abiertas?|ejecut[aá]ndose|corriendo|ahora)\b',low):
        return _run(manager,'listar_procesos',{'filtro':'','limite':20})
    if 'ventana' in low and re.search(r'\b(ahora|abierta|abiertas|tengo)\b',low): return _run(manager,'listar_ventanas',{})
    if ('estado de mi sistema' in low or 'estado del sistema' in low or 'cpu' in low and 'ram' in low and 'disco' in low):
        return _run(manager,'estado_sistema',{})
    if ('espacio libre' in low and 'disco' in low) or 'espacio tengo' in low and 'disco' in low:
        return _run(manager,'espacio_libre_disco',{})
    if re.search(r'(cu[aá]nta|cu[aá]nto|qué cantidad|que cantidad).*(ram|memoria)',low) or ('ram' in low and 'usando' in low):
        return _run(manager,'uso_ram',{})
    if re.search(r'\b(lista|listar|qué archivos|que archivos)\b',low) and 'documentos' in low:
        return _run(manager,'listar_archivos',{'directorio':'~/Documentos'})
    # Archivos y carpetas
    m=re.search(r'\b(?:crea|crear)\s+(?:una\s+)?carpeta\s+(?:llamada\s+)?(.+?)\s+(?:en|dentro de)\s+documentos\b',t,re.I)
    if m: return _run(manager,'crear_carpeta',{'ruta':f"~/Documentos/{m.group(1).strip().strip(chr(34)+chr(39))}"})
    m=re.search(r'\b(?:crea|crear)\s+(?:el\s+)?archivo\s+([\w. -]+)\s+(?:en\s+)?documentos\s+(?:con|que contenga)\s+["\'](.+?)["\']',t,re.I)
    if m: return _run(manager,'crear_archivo',{'ruta':f"~/Documentos/{m.group(1).strip()}",'contenido':m.group(2)})
    # Ratón / teclado
    if 'mueve el ratón' in low or 'mueve el raton' in low:
        if 'centro' in low:
            raw_text=_run(manager,'obtener_tamano_pantalla',{})
            m2=re.search(r'(\d+)x(\d+)',raw_text)
            if not m2: return "No pude determinar el centro de la pantalla."
            return _run(manager,'mover_raton',{'x':int(m2.group(1))//2,'y':int(m2.group(2))//2})
        if 'esquina superior izquierda' in low: return _run(manager,'mover_raton',{'x':0,'y':0})
        if 'esquina inferior derecha' in low:
            raw=manager.execute('obtener_tamano_pantalla',{}); m2=re.search(r'(\d+)x(\d+)',raw.message) if raw.success else None
            if not m2: return f"No pude obtener la pantalla: {raw.error or raw.message}"
            return _run(manager,'mover_raton',{'x':int(m2.group(1))-1,'y':int(m2.group(2))-1})
    if re.search(r'\b(?:abre|abrir)\s+(?:una\s+)?(?:nueva\s+)?pestaña(?:\s+de\s+brave)?\b',low):
        return _run(manager,'pulsar_tecla',{'teclas':'ctrl+t'})
    m=re.search(r'\b(?:pulsa|presiona)\s+(?:la\s+)?(.+?)[.!]?$',t,re.I)
    if m:
        keys=m.group(1).strip().replace(' y ','+')
        keys=re.sub(r'\bCtrl\b','ctrl',keys,flags=re.I); keys=re.sub(r'\bAlt\b','alt',keys,flags=re.I); keys=re.sub(r'\bShift\b','shift',keys,flags=re.I)
        return _run(manager,'pulsar_tecla',{'teclas':keys})
    m=re.search(r'\b(?:escribe|escribir)\s+["\'](.+?)["\']',t,re.I)
    if m: return _run(manager,'escribir_en_escritorio',{'texto':m.group(1)})
    if 'captura de pantalla' in low or 'haz una captura' in low:
        return _run(manager,'capturar_pantalla',{})
    # Web search
    m=re.search(r'\b(?:busca|buscar|búscame|búscalo)\s+(?:en internet|en la web)?\s*(?:cu[aá]l es|qu[eé] es)?\s*(.+)',t,re.I)
    if m and ('en internet' in low or 'en la web' in low or low.startswith('busca ')):
        q=m.group(1).strip(' .?"')
        if q: return _run(manager,'buscar_en_web',{'consulta':q,'cantidad':6})
    calc=_calculator(t)
    if calc is not None: return calc
    return None

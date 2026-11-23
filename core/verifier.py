from __future__ import annotations
from dataclasses import dataclass
import os, subprocess

@dataclass(frozen=True)
class Verification:
    verified: bool
    reason: str = ""
    retryable: bool = False

class Verifier:
    def verify(self, name: str, args: dict, result) -> Verification:
        if getattr(result, 'requires_confirmation', False):
            return Verification(False, 'La acción quedó pendiente de confirmación.', False)
        if not getattr(result, 'success', False):
            error=str(getattr(result,'error','') or getattr(result,'message','') or 'Error desconocido')
            return Verification(False,error,self.is_retryable_error(error))
        data=getattr(result,'data',None)
        if name=='abrir_aplicacion':
            import tools
            try:
                estado=tools.comprobar_aplicacion(args.get('nombre','')).lower()
                ok='está ejecutándose' in estado or 'esta ejecutándose' in estado
                return Verification(ok,'La aplicación aparece en ejecución.' if ok else 'La aplicación fue lanzada, pero no aparece en ejecución.',True)
            except Exception as exc: return Verification(False,f'No se pudo verificar la aplicación: {exc}',True)
        if name=='cerrar_aplicacion':
            import tools
            try:
                estado=tools.comprobar_aplicacion(args.get('nombre','')).lower()
                ok='no parece estar ejecutándose' in estado
                return Verification(ok,'La aplicación ya no aparece en ejecución.' if ok else 'La aplicación sigue ejecutándose.',True)
            except Exception as exc: return Verification(False,f'No se pudo verificar el cierre: {exc}',True)
        if name in {'crear_archivo','crear_carpeta'}:
            path=os.path.realpath(os.path.expanduser(args.get('ruta','')))
            ok=os.path.isfile(path) if name=='crear_archivo' else os.path.isdir(path)
            return Verification(ok,'Recurso creado y verificado.' if ok else 'El recurso no existe tras la creación.',True)
        if name=='eliminar_archivo':
            path=os.path.realpath(os.path.expanduser(args.get('ruta','')))
            ok=not os.path.exists(path)
            return Verification(ok,'Eliminación verificada.' if ok else 'El archivo sigue existiendo.',True)
        if name=='capturar_pantalla':
            path=(data or {}).get('path') if isinstance(data,dict) else None
            ok=bool(path and os.path.isfile(path) and os.path.getsize(path)>0)
            return Verification(ok,'Captura creada y verificada.' if ok else 'La captura no existe o está vacía.',False)
        if name=='mover_raton':
            try:
                out=subprocess.check_output(['xdotool','getmouselocation','--shell'],text=True,timeout=3)
                vals={k:v for k,v in (line.split('=',1) for line in out.splitlines() if '=' in line)}
                ok=int(vals.get('X','-1'))==int(args['x']) and int(vals.get('Y','-1'))==int(args['y'])
                return Verification(ok,'Posición del ratón verificada.' if ok else 'El ratón no terminó en la posición solicitada.',True)
            except Exception as exc: return Verification(False,f'No se pudo verificar el ratón: {exc}',True)
        if name in {'pulsar_tecla','escribir_en_escritorio'}:
            return Verification(True,'Entrada enviada por xdotool y proceso completado.')
        if name=='navegador_escribir':
            ok=isinstance(data,dict) and bool(data.get('filled'))
            return Verification(ok,'Campo rellenado confirmado.' if ok else 'El navegador no confirmó el campo rellenado.',False)
        if name in {'navegador_click_texto','navegador_click_role','click_elemento_visual'}:
            ok=isinstance(data,dict) and bool(data.get('clicked'))
            return Verification(ok,'Click confirmado.' if ok else 'El click no fue confirmado.',False)
        if name=='esperar_elemento_visual':
            ok=isinstance(data,dict) and bool(data.get('found'))
            return Verification(ok,'Elemento detectado.' if ok else 'Elemento no detectado.',False)
        if name=='buscar_elemento_visual':
            n=int((data or {}).get('count',0)) if isinstance(data,dict) else 0
            return Verification(n>0,'Elemento encontrado.' if n else 'Elemento no encontrado.',True)
        if name in {'navegador_abrir','navegador_atras'}:
            ok=isinstance(data,dict) and bool(data.get('url'))
            return Verification(ok,'URL confirmada.' if ok else 'No se pudo confirmar la URL.',True)
        return Verification(True,'Resultado de herramienta aceptado.')

    @staticmethod
    def is_retryable_error(error:str)->bool:
        t=error.lower()
        if any(x in t for x in ('permiso','permission','confirmación','confirmacion','ruta fuera','no permitido','json inválido','json invalido')): return False
        return any(x in t for x in ('timeout','timed out','conexión','connection','no se encontró','no encuentro','no aparece','sigue ejecutándose','no existe tras','no terminó'))

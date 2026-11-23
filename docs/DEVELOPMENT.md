# Desarrollo

## Entorno local

Se recomienda Python 3.12, que también usa el bootstrap:

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

Las pruebas se ejecutan con:

```bash
./.venv/bin/python -m pytest
```

Para comprobar sintaxis:

```bash
./.venv/bin/python -m compileall -q .
```

Al ejecutar pruebas, usa una base de datos temporal o define
`JARVIS_DB_PATH` para no modificar datos personales en `data/`.

## Estructura del proyecto

La aplicación mantiene algunos módulos de nivel superior por su integración
con el bootstrap y los scripts existentes. La lógica del agente, seguridad,
verificación, navegador y visión vive en `core/`. Consulta la
[guía de arquitectura](ARCHITECTURE.md) antes de mover módulos o cambiar
interfaces entre componentes.

## Cambios de herramientas

Cada herramienta debe tener implementación, esquema JSON, política explícita y
pruebas. Las herramientas que alteran el sistema también deben tener un
resultado verificable y una confirmación adecuada. No uses comandos de shell
construidos a partir de texto del modelo; invoca procesos con argumentos
separados y valida entradas.

## Pull requests

- Mantén los cambios enfocados y explica el problema que resuelven.
- Añade pruebas para cambios de comportamiento.
- Ejecuta la suite y revisa `git diff --check`.
- No incluyas `.env`, bases de datos, logs, modelos descargados, capturas ni
  otros datos personales.
- Actualiza las guías cuando cambien instalación, configuración o capacidades.

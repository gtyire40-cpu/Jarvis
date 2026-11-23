# Jarvis Local

Asistente personal local para Linux con interfaz gráfica, voz, Ollama, control de escritorio y memoria persistente.

## Inicio rápido

```bash
./dist/executable
```

Para instalar el lanzador de escritorio:

```bash
./scripts/install.sh
```

## Desarrollo

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
pytest
```

Copia `.env.example` a `.env` y ajusta únicamente las opciones necesarias.

## Documentación

- [Registro de cambios](docs/CHANGELOG.md)
- [Configuración](.env.example)
- [Requisitos](requirements.txt)

## Generados localmente

Las bases de datos, registros, entorno virtual, cachés y modelos descargados no forman parte del repositorio.

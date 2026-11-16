# Práctica de trading cripto (sin dinero)

Bot de **práctica** que simula, sin dinero real, sin cuentas en exchanges y sin claves, tres libros de $100 en
bitcoin y ether. No es una recomendación de inversión.

- **Tendencia** (la estrategia): promedio de 8 señales de tendencia en BTC y ETH, solo compra.
- **Mantener BTC+ETH**: mitad y mitad, para comparar.
- **Adaptativa (alza + baja)**: la tendencia más apuestas a la baja en perpetuos. No pasó su prueba histórica; se
  practica solo como comparación.

Cada libro tiene un gemelo "ideal" (las mismas reglas con precios de cierre) para medir cuánto se aleja la práctica de
la simulación.

## Cómo funciona

- Corre solo en GitHub Actions (`.github/workflows/revision-diaria.yml`) cada día a las 00:10 UTC (7:10 pm de
  Colombia), con dos revisiones de seguridad la misma noche. Si no hay nada nuevo, no cambia ningún archivo.
- Guarda su estado en `datos/paper/` y publica `informe.html` en GitHub Pages: esa página es el informe.
- Para correrlo a mano: pestaña **Actions** → **Revisión diaria** → **Run workflow**.
- Datos públicos: contado de Binance (`data-api.binance.vision`) y perpetuos de Hyperliquid (`api.hyperliquid.xyz`).
  Detalle en `bot/fuentes.py`.

## Etapas

- **Etapa 1** (3 oct – 15 nov 2026): cerrada. Copia fija en `datos/paper_etapa1/` y `reportes/diario_etapa1/`; se ve
  plegada al final del informe.
- **Etapa 2** (desde el cierre del 15 nov 2026): los tres libros volvieron a empezar con $100 en el mismo momento y con
  los mismos precios, para compararlos en igualdad de condiciones.

## Carpetas

- `bot/` — el bot (`python -m bot correr | reporte | verificar`); solo biblioteca estándar de Python.
- `herramientas/estudio.py` — las señales del estudio original (el bot usa exactamente las mismas).
- `datos/` — velas diarias del contado y del perpetuo, financiación horaria, libros de práctica.
- `reportes/diario*/` — un informe por día (`.json` para reconstruir la página, `.md` para leer).
- `actualizar_copia_local.bat` — en un PC con Windows, trae a la carpeta local lo último que guardó el bot.

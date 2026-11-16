"""Parámetros de la práctica sin dinero (fase 2). Cambiarlos solo con aprobación del dueño del proyecto: si cambian a
mitad de la práctica, la práctica deja de servir como prueba."""
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA = os.path.join(RAIZ, "datos", "paper")
REPORTES = os.path.join(RAIZ, "reportes")

# Etapa 2 (desde el 16 nov 2026): los tres libros vuelven a empezar con $100 en el mismo momento, con el cierre del
# 15 nov 2026, para compararlos en igualdad de condiciones. La compuerta B cuenta de nuevo desde aquí.
ETAPA = 2
INICIO = "2026-11-16"  # primer día de la práctica de esta etapa (fecha de Colombia de la primera revisión)
INICIO_CIERRE = "2026-11-15"  # cierre diario con el que arrancan los tres libros
# Etapa 1 (3 oct – 15 nov 2026), cerrada: copia fija que el bot ya no escribe.
ETAPA1 = {"desde": "2026-10-03", "hasta": "2026-11-15",
          "datos": os.path.join(RAIZ, "datos", "paper_etapa1"),
          "reportes": os.path.join(REPORTES, "diario_etapa1")}
CAPITAL = 100.0  # USD simulados por libro
LIBROS = {
    "tendencia": "Tendencia (la estrategia)",
    "mantener": "Mantener BTC+ETH (para comparar)",
}
ACTIVOS = ("BTC", "ETH")

# Ejecución simulada como en Binance contado
COMISION = 0.001  # por lado; en la compra se cobra en la moneda comprada
MIN_ORDEN = 5.0  # USDT (filtro NOTIONAL, consultado el 3 oct 2026)
PASO = {"BTC": 0.00001, "ETH": 0.0001}  # LOT_SIZE
# Libro "ideal": lo que habría hecho el estudio con precios de cierre y su costo supuesto
COSTO_IDEAL = 0.0015
BANDA = 0.10  # igual que el estudio

HORA_REVISION = "19:10"  # Colombia (UTC−5) = 00:10 UTC: 10 minutos después del cierre diario de Binance (00:00 UTC)

# Compuerta B (pasar a dinero real)
DIAS_MINIMOS = 28
DIAS_MAXIMOS = 56
AJUSTES_MINIMOS = 5  # ajustes del libro de tendencia, sin contar la compra inicial
TOLERANCIA_PP = 1.5  # diferencia máxima libro vs. ideal, en puntos porcentuales
ATRASO_MAX_H = 3  # una revisión cuenta "a tiempo" si ocurre antes de 3 h después de la hora fijada
A_TIEMPO_MIN = 0.90

# Tercer libro "adaptativa" (Estrategia 3 de BITACORA.md; instalado el 15 nov 2026). Es solo de observación: no cuenta
# para la compuerta B y no cambia nada de los libros "tendencia" y "mantener". Lado al alza = mismos objetivos que
# "tendencia"; lado a la baja = cortos en el perpetuo con la regla de abajo (versión elegida por
# herramientas/estudio3.py; veredicto en reportes/estrategia3-2026-11-15.md). Desde la etapa 2 los precios y la
# financiación del perpetuo son los de Hyperliquid (cobro cada hora), la plataforma cuyas condiciones ya supone.
ADAPTATIVA = {
    "nombre": "Adaptativa (alza + baja)",
    "version": "3A",
    "regla": {"ruptura": 20, "senales": 1, "cierre": 10, "atr": 2.5, "tam": 0.15, "f200": True, "ffin": True},
    "veredicto": ("Prueba histórica: versión 3A (fijada antes de mirar datos) · no pasó (cumplió 2 de 5 condiciones). "
                  "Se practica para compararla con la tendencia, no para pasar a dinero real."),
    "comision_corto": 0.0005,   # por lado, sobre el nocional (condiciones de Hyperliquid)
    "min_orden_corto": 10.0,    # USD, para abrir un corto
    "paso_corto": {"BTC": 0.00001, "ETH": 0.0001},
    "costo_ideal_corto": 0.0010,  # libro ideal: el costo del estudio (perpetuo 0,10% por lado)
}

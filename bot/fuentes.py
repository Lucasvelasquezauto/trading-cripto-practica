"""Fuentes de datos del bot diario: las mismas en el PC y en GitHub (desde el 16 nov 2026). Solo datos públicos, sin
cuenta ni claves; solo biblioteca estándar.

- Contado de Binance (velas diarias y precio en vivo de BTC y ETH): https://data-api.binance.vision/api/v3/...
  (la copia pública de solo lectura de la API de Binance; responde también desde servidores de GitHub, donde
  api.binance.com está bloqueado). Formatos verificados en vivo el 16 nov 2026, iguales a los de api.binance.com:
    klines ?symbol&interval=1d&startTime&limit → [[apertura_ms, "o", "h", "l", "c", "v", cierre_ms, ...]]
        (incluye la vela del día en curso, que se descarta)
    ticker/bookTicker ?symbols=["BTCUSDT","ETHUSDT"] → [{symbol, bidPrice, bidQty, askPrice, askQty}]
- Perpetuos de Hyperliquid (para los cortos del libro "adaptativa"): POST https://api.hyperliquid.xyz/info
  Formatos verificados en vivo el 16 nov 2026:
    candleSnapshot {"req": {"coin","interval","startTime","endTime"}} → [{t, T, s, i, o, c, h, l, v, n}]
        (t = apertura en ms, UTC; solo las ~5000 velas más recientes; incluye la vela en curso, que se descarta;
        las velas diarias anteriores a mayo de 2023 traen n = 0, sin operaciones, y se descartan)
    fundingHistory {"coin","startTime"} → [{coin, fundingRate, premium, time}], un cobro CADA HORA (time = la hora
        en punto + unos milisegundos), máximo 500 por llamada. Tasa positiva: los largos pagan a los cortos.
    l2Book {"coin"} → {"levels": [[compras...], [ventas...]], "time"}; cada nivel {px, sz, n}
"""
import csv
import json
import os
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
SPOT = "https://data-api.binance.vision/api/v3"
HL = "https://api.hyperliquid.xyz/info"
DIA_MS = 86_400_000
HORA_MS = 3_600_000
MARGEN_MS = HORA_MS - 1  # el cobro de las 00:00 UTC (marcado a esa hora + milisegundos, rara vez minutos) es del
#                         día anterior: entra con su cierre; el de la 01:00 ya es del día nuevo y espera
AGENTE = {"User-Agent": "bot-practica/1.0"}


def _abrir(req, intentos=6):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # red inestable o límite de la API: esperar y reintentar
            ultimo = e
            print(f"  reintento {i + 1}: {e}", flush=True)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"sin respuesta de {req.full_url}: {ultimo}")


def pedir(url):
    return _abrir(urllib.request.Request(url, headers=AGENTE))


def hl(cuerpo):
    return _abrir(urllib.request.Request(HL, data=json.dumps(cuerpo).encode(),
                                         headers={**AGENTE, "Content-Type": "application/json"}))


def corte_ms(ahora):
    """Inicio del día UTC de `ahora` (00:00): hasta ahí llegan los datos que se guardan. Así, varias revisiones el
    mismo día ven exactamente los mismos datos (el bot es repetible) y nada del día en curso se cuela."""
    return int(ahora.timestamp() * 1000) // DIA_MS * DIA_MS


def _ultimo_ms(ruta):
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.reader(f))
    return int(filas[-1][0]) if len(filas) > 1 else None


def _anexar(ruta, encabezado, filas):
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(encabezado)
        w.writerows(filas)
    print(f"{os.path.basename(ruta)}: +{len(filas)} filas", flush=True)


# ---------------------------------------------------------------------------------------------- contado
def actualizar_spot(activo, ahora):
    """Velas diarias completas del contado de Binance en datos/velas_spot_<A>USDT_1d.csv (mismo formato del estudio)."""
    ruta = os.path.join(DATOS, f"velas_spot_{activo}USDT_1d.csv")
    corte = corte_ms(ahora)
    desde = _ultimo_ms(ruta)
    desde = 1_483_228_800_000 if desde is None else desde + 1  # 1 ene 2017: la API entrega desde su primer dato
    filas = []
    while desde < corte:
        lote = pedir(f"{SPOT}/klines?symbol={activo}USDT&interval=1d&startTime={desde}&limit=1000")
        if not lote:
            break
        nuevas = [[int(x[0]), x[1], x[2], x[3], x[4], x[5]] for x in lote]
        filas += [x for x in nuevas if x[0] >= desde and x[0] + DIA_MS <= corte]
        if len(lote) < 1000:
            break
        desde = int(lote[-1][0]) + 1
        time.sleep(0.3)
    _anexar(ruta, ["ms", "apertura", "maximo", "minimo", "cierre", "volumen"], filas)


def cotizacion_spot(activos):
    """{activo: (mejor compra, mejor venta)} del contado de Binance en este momento."""
    lista = ",".join(f"%22{a}USDT%22" for a in activos)
    d = pedir(f"{SPOT}/ticker/bookTicker?symbols=%5B{lista}%5D")
    out = {x["symbol"][:-4]: (float(x["bidPrice"]), float(x["askPrice"])) for x in d}
    if set(out) != set(activos) or any(b <= 0 or a < b for b, a in out.values()):
        raise RuntimeError(f"cotización rara del contado: {out}")
    return out


# ---------------------------------------------------------------------------------------------- Hyperliquid
def ruta_velas_perp(activo):
    return os.path.join(DATOS, f"hl_velas_{activo}_1d.csv")


def ruta_financiacion(activo):
    return os.path.join(DATOS, f"hl_financiacion_{activo}.csv")


def _velas_hl(activo, intervalo, desde, hasta):
    d = hl({"type": "candleSnapshot", "req": {"coin": activo, "interval": intervalo, "startTime": int(desde),
                                              "endTime": int(hasta)}})
    if not isinstance(d, list):
        raise RuntimeError(f"Hyperliquid candleSnapshot {activo}: respuesta inesperada {str(d)[:120]}")
    return d


def actualizar_perp(activo, ahora):
    """Velas diarias completas del perpetuo de Hyperliquid y sus cobros de financiación horarios hasta el de las 00:00 UTC
    de hoy (que es del día anterior). El precio de cada cobro es la apertura de la vela de 1 hora de ese momento
    (Hyperliquid cobra cantidad × precio de referencia de esa hora × tasa). Hasta mediados de 2023 cobraba cada 8 h."""
    corte = corte_ms(ahora)
    ruta = ruta_velas_perp(activo)
    desde = _ultimo_ms(ruta)
    desde = 0 if desde is None else desde + 1
    filas = []
    if desde + DIA_MS <= corte:
        lote = _velas_hl(activo, "1d", desde, corte)
        filas = sorted([int(x["t"]), x["o"], x["h"], x["l"], x["c"], x["v"]] for x in lote
                       if int(x["t"]) >= desde and int(x["t"]) + DIA_MS <= corte and int(x.get("n", 0)) > 0)
    _anexar(ruta, ["ms", "apertura", "maximo", "minimo", "cierre", "volumen"], filas)

    ruta = ruta_financiacion(activo)
    desde = _ultimo_ms(ruta)
    desde = 0 if desde is None else desde + 1
    hasta = corte + MARGEN_MS
    eventos = []
    while desde <= hasta:
        lote = hl({"type": "fundingHistory", "coin": activo, "startTime": int(desde)})
        if not isinstance(lote, list):
            raise RuntimeError(f"Hyperliquid fundingHistory {activo}: respuesta inesperada {str(lote)[:120]}")
        nuevos = sorted((int(x["time"]), x["fundingRate"]) for x in lote if int(x["time"]) >= desde)
        eventos += [e for e in nuevos if e[0] <= hasta]
        if len(lote) < 500 or not nuevos or nuevos[-1][0] > hasta:
            break
        desde = nuevos[-1][0] + 1
        time.sleep(0.2)
    precio = {}
    recientes = [t for t, _ in eventos if t > corte - 200 * DIA_MS]  # Hyperliquid guarda ~5000 velas de 1 h
    if recientes:
        h0 = min(recientes) // HORA_MS * HORA_MS
        while h0 <= max(recientes):
            lote = _velas_hl(activo, "1h", h0, max(recientes) + HORA_MS)
            for x in lote:
                precio[int(x["t"])] = x["o"]
            ultimo = max((int(x["t"]) for x in lote), default=h0)
            if len(lote) < 4000 or ultimo <= h0:
                break
            h0 = ultimo + HORA_MS
    _anexar(ruta, ["ms", "tasa", "precio"],
            [[t, tasa, precio.get(t // HORA_MS * HORA_MS, "")] for t, tasa in eventos])


def cotizacion_perp(activos):
    """{activo: (mejor compra, mejor venta)} del perpetuo de Hyperliquid en este momento."""
    out = {}
    for a in activos:
        d = hl({"type": "l2Book", "coin": a})
        try:
            out[a] = (float(d["levels"][0][0]["px"]), float(d["levels"][1][0]["px"]))
        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError(f"Hyperliquid l2Book {a}: respuesta inesperada {str(d)[:120]}")
        if out[a][0] <= 0 or out[a][1] < out[a][0]:
            raise RuntimeError(f"cotización rara del perpetuo de {a}: {out[a]}")
    return out

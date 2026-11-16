"""Fase 1: evaluación ex-post de los 3 bolsillos + combinado, en dólares, con los datos de datos/.
  set PYTHONIOENCODING=utf-8 & C:\\Python314\\python.exe herramientas\\estudio.py
Reglas del estudio (periodos, costos, versiones principales): BITACORA.md, "Fase 1: reglas del estudio".
Escribe reportes/fase1-<fecha>.md (resumen) y reportes/fase1-<fecha>-variantes.csv (todas las variantes).
Solo biblioteca estándar; no necesita red.
"""
import bisect
import collections
import csv
import datetime as dt
import math
import os
import statistics
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, "datos")
ACTIVOS = ("BTC", "ETH")
PERIODOS = {  # (inicio, fin) de la evaluación; la simulación siempre corre desde el primer dato
    "diseño": ("2018-03-06", "2022-12-31"),       # 200 días después del primer dato: las medias ya existen
    "diseño_renta": ("2019-11-28", "2022-12-31"),  # desde que hay financiación de BTC y ETH
    "examen": ("2023-01-01", None),
}
COSTO = {"spot": 0.0015, "corto": 0.0010, "carry": 0.0025}  # por unidad movida (carry: por nocional)
BANDA = 0.10  # rebalancea solo si algún peso cambia al menos esto, o si una posición abre o cierra
VARA = 0.11


# ------------------------------------------------------------------------------------------------- datos
def _csv(nombre):
    with open(os.path.join(DATOS, nombre), encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


def _dia(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def _mas(fecha, dias):
    return (dt.date.fromisoformat(fecha) + dt.timedelta(days=dias)).isoformat()


def percentiles(serie, ventana=1460, minimo=365):
    """Percentil de cada valor dentro de sus últimos `ventana` días (serie = [(fecha, valor)] ordenada)."""
    salida, orden = {}, []
    for j, (f, v) in enumerate(serie):
        bisect.insort(orden, v)
        if j >= ventana:
            orden.pop(bisect.bisect_left(orden, serie[j - ventana][1]))
        if len(orden) >= minimo:
            salida[f] = bisect.bisect_left(orden, v) / len(orden)
    return salida


def cargar():
    """Series diarias alineadas al calendario del contado. Valor del día D = cierre a las 00:00 UTC de D+1."""
    fechas = sorted(_dia(int(r[0])) for r in _csv("velas_spot_BTCUSDT_1d.csv"))
    D = {"fechas": fechas, "n": len(fechas)}
    for a in ACTIVOS:
        spot = {_dia(int(r[0])): float(r[4]) for r in _csv(f"velas_spot_{a}USDT_1d.csv")}
        perp = {_dia(int(r[0])): float(r[4]) for r in _csv(f"velas_perp_{a}USDT_1d.csv")}
        fin = collections.defaultdict(float)
        for r in _csv(f"financiacion_{a}USDT.csv"):
            fin[_dia(int(r[0]) - 5000)] += float(r[1])  # el cobro de las 00:00 de D+1 es del día D
        c = [spot[f] for f in fechas]
        p = [perp.get(f) for f in fechas]
        hay = [i > 0 and p[i] is not None and p[i - 1] is not None and f in fin for i, f in enumerate(fechas)]
        D[f"precio_{a}"] = c
        D[f"r_spot_{a}"] = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
        D[f"hay_perp_{a}"] = hay
        D[f"r_perp_{a}"] = [p[i] / p[i - 1] - 1 if hay[i] else 0.0 for i in range(len(c))]
        D[f"fin_{a}"] = [fin.get(f, 0.0) for f in fechas]
        serie = [(r[0], float(r[1])) for r in _csv(f"mvrv_{a.lower()}.csv")]
        pct = percentiles(serie)
        mv = dict(serie)
        # Rezago: el MVRV del día D se usa al cierre de D+1.
        D[f"mvrv_{a}"] = [mv.get(_mas(f, -1)) for f in fechas]
        D[f"pct_mvrv_{a}"] = [pct.get(_mas(f, -1)) for f in fechas]
    fng = {r[0]: float(r[1]) for r in _csv("miedo_codicia.csv")}
    D["fng"] = [fng.get(f) for f in fechas]  # publicado a las 00:00 UTC de D: conocido al cierre de D
    return D


# ----------------------------------------------------------------------------------------------- señales
def senales_tendencia(precio):
    """Señales binarias (1 = tendencia al alza) por día; None mientras no hay historia suficiente."""
    n = len(precio)
    acum = [0.0]
    for x in precio:
        acum.append(acum[-1] + x)

    def media(m, i):
        return (acum[i + 1] - acum[i + 1 - m]) / m

    s = {}
    for m in (20, 50, 100, 200):
        s[f"sobre_media_{m}"] = [None if i < m - 1 else float(precio[i] > media(m, i)) for i in range(n)]
    for a, b in ((10, 50), (20, 100), (50, 200)):
        s[f"cruce_{a}_{b}"] = [None if i < b - 1 else float(media(a, i) > media(b, i)) for i in range(n)]
    for m in (14, 28, 56, 90):
        s[f"direccion_{m}"] = [None if i < m else float(precio[i] > precio[i - m]) for i in range(n)]
    for m in (20, 55):
        out, dentro = [], 0.0
        for i in range(n):
            if i < m:
                out.append(None)
                continue
            if precio[i] > max(precio[i - m:i]):
                dentro = 1.0
            elif precio[i] < min(precio[i - m // 2:i]):
                dentro = 0.0
            out.append(dentro)
        s[f"ruptura_{m}"] = out
    canasta = ("sobre_media_50", "sobre_media_100", "sobre_media_200", "cruce_20_100", "direccion_28",
               "direccion_56", "direccion_90", "ruptura_20")
    s["promedio_8"] = [None if any(s[k][i] is None for k in canasta) else sum(s[k][i] for k in canasta) / 8
                       for i in range(n)]
    return s


def volatilidad(r, i, n=30):
    return statistics.pstdev(r[i - n + 1: i + 1]) * math.sqrt(365) if i >= n else None


def media_fin(D, a, i, n):
    """Financiación media anualizada de los últimos n días (cada día suma sus 3 cobros)."""
    if i < n or not all(D[f"hay_perp_{a}"][i - n + 1: i + 1]):
        return None
    return sum(D[f"fin_{a}"][i - n + 1: i + 1]) / n * 365


class Histeresis:
    """Estado encendido/apagado: enciende al cruzar `on`, apaga al cruzar `off` (para no operar a cada rato)."""

    def __init__(self, on, off, al_reves=False):
        self.on, self.off, self.al_reves, self.estado = on, off, al_reves, False

    def __call__(self, x):
        if x is None:
            return self.estado
        if self.al_reves:  # enciende cuando x BAJA de on, apaga cuando SUBE de off
            self.estado = True if x < self.on else (False if x > self.off else self.estado)
        else:
            self.estado = True if x > self.on else (False if x < self.off else self.estado)
        return self.estado


# ---------------------------------------------------------------------------------------------- simulador
def simular(D, objetivo, eficiencia=0.5):
    """objetivo(i) -> {componente: peso del capital}, decidido al cierre del día i y vigente el día i+1.
    Componentes: spot_A (contado), corto_A (perpetuo 1x), carry_A (contado + corto; rinde `eficiencia` × la
    base y la financiación por cada dólar del bolsillo). Lo no asignado queda en caja al 0%."""
    n = D["n"]
    caja, pos = 1.0, {}
    curva, ops, expo = [1.0], set(), [0.0]
    for i in range(1, n):
        for c in pos:
            tipo, a = c.split("_")
            if tipo == "spot":
                r = D[f"r_spot_{a}"][i]
            elif tipo == "corto":
                r = -D[f"r_perp_{a}"][i] + D[f"fin_{a}"][i]
            else:
                r = eficiencia * (D[f"r_spot_{a}"][i] - D[f"r_perp_{a}"][i] + D[f"fin_{a}"][i])
            pos[c] *= max(0.0, 1 + r)
        valor = caja + sum(pos.values())
        obj = {c: w for c, w in (objetivo(i) or {}).items()
               if w > 1e-9 and (c.startswith("spot") or D[f"hay_perp_{c[-3:]}"][i])}
        actual = {c: v / valor for c, v in pos.items() if v > 0}
        todos = set(obj) | set(actual)
        cambia = any(abs(obj.get(c, 0) - actual.get(c, 0)) >= BANDA or (c in obj) != (c in actual) for c in todos)
        if cambia:
            valor -= valor * sum(abs(obj.get(c, 0) - actual.get(c, 0)) * COSTO[c.split("_")[0]] *
                                 (eficiencia if c.startswith("carry") else 1) for c in todos)
            pos = {c: w * valor for c, w in obj.items()}
            caja = valor - sum(pos.values())
            ops.add(i)
        curva.append(valor)
        expo.append(sum(v for c, v in pos.items() if not c.startswith("carry")) / valor)
    return curva, ops, expo


# --------------------------------------------------------------------------------------------- métricas
def metricas(D, curva, ops, expo, periodo):
    ini, fin = PERIODOS[periodo]
    f = D["fechas"]
    i0 = bisect.bisect_left(f, ini)
    i1 = (bisect.bisect_right(f, fin) - 1) if fin else len(f) - 1
    v = curva[i0: i1 + 1]
    anos = (i1 - i0) / 365.25
    cagr = (v[-1] / v[0]) ** (1 / anos) - 1 if v[0] > 0 and v[-1] > 0 else -1.0
    pico, dd = v[0], 0.0
    for x in v:
        pico = max(pico, x)
        dd = min(dd, x / pico - 1)
    rd = [v[k] / v[k - 1] - 1 for k in range(1, len(v)) if v[k - 1] > 0]
    vol = statistics.pstdev(rd) * math.sqrt(365) if rd else 0.0
    sharpe = statistics.mean(rd) / statistics.pstdev(rd) * math.sqrt(365) if rd and statistics.pstdev(rd) else 0.0
    cierre_mes = {}
    for k in range(i0, i1 + 1):
        cierre_mes[f[k][:7]] = curva[k]
    meses = list(cierre_mes.values())
    rm = [meses[0] / curva[i0] - 1] + [meses[k] / meses[k - 1] - 1 for k in range(1, len(meses))]
    sin_mejor = sorted(rm)[:-1]
    prod = math.prod(1 + x for x in sin_mejor)
    cagr_sm = prod ** (12 / len(sin_mejor)) - 1 if prod > 0 and sin_mejor else -1.0
    cierre_ano = {}
    for k in range(i0, i1 + 1):
        cierre_ano[f[k][:4]] = curva[k]
    anos_r, previo = {}, curva[i0]
    for a, x in cierre_ano.items():
        anos_r[a] = x / previo - 1
        previo = x
    return {"cagr": cagr, "max_caida": dd, "vol": vol, "sharpe": sharpe, "peor_mes": min(rm),
            "meses_pos": sum(x > 0 for x in rm) / len(rm), "cagr_sin_mejor_mes": cagr_sm,
            "ops_ano": sum(1 for k in ops if i0 < k <= i1) / anos, "expo": statistics.mean(expo[i0: i1 + 1]),
            "anos": anos_r}


# ----------------------------------------------------------------------------------------------- bolsillos
def variantes(D):
    """[(bolsillo, nombre, es_principal, objetivo, eficiencia)]"""
    sen = {a: senales_tendencia(D[f"precio_{a}"]) for a in ACTIVOS}
    vol = {a: [volatilidad(D[f"r_spot_{a}"], i) for i in range(D["n"])] for a in ACTIVOS}
    grupos = {"BTC": ("BTC",), "ETH": ("ETH",), "BTC+ETH": ACTIVOS}
    V = []

    # Referencias
    for g, act in grupos.items():
        V.append(("referencia", f"mantener {g}", False, lambda i, act=act: {f"spot_{a}": 1 / len(act) for a in act}, 0.5))

    # 1. Tendencia
    for k in sen["BTC"]:
        for g, act in grupos.items():
            def obj(i, k=k, act=act):
                return {f"spot_{a}": (sen[a][k][i] or 0) / len(act) for a in act}
            V.append(("tendencia", f"{k} · {g}", k == "promedio_8" and g == "BTC+ETH", obj, 0.5))
    for k in ("promedio_8", "sobre_media_100", "cruce_20_100"):
        def obj(i, k=k):  # con volatilidad objetivo de 50% anual
            return {f"spot_{a}": (sen[a][k][i] or 0) * min(1.0, 0.5 / vol[a][i]) / 2 if vol[a][i] else 0
                    for a in ACTIVOS}
        V.append(("tendencia", f"{k} · BTC+ETH · volatilidad 50%", False, obj, 0.5))

        def obj(i, k=k):  # también corto con el perpetuo cuando la tendencia es bajista
            w = {}
            for a in ACTIVOS:
                s = sen[a][k][i]
                if s is None:
                    continue
                neto = 2 * s - 1
                w[f"spot_{a}" if neto > 0 else f"corto_{a}"] = abs(neto) / 2
            return w
        V.append(("tendencia", f"{k} · BTC+ETH · con cortos", False, obj, 0.5))

    def rotacion(i):
        if i < 56:
            return {}
        a = max(ACTIVOS, key=lambda a: D[f"precio_{a}"][i] / D[f"precio_{a}"][i - 56])
        return {f"spot_{a}": sen[a]["promedio_8"][i] or 0}
    V.append(("tendencia", "rotación al más fuerte (56 días) · promedio_8", False, rotacion, 0.5))

    # 2. Ciclo
    for g, act in grupos.items():
        V.append(("ciclo", f"MVRV percentil 4 años, continuo · {g}", g == "BTC", lambda i, act=act: {
            f"spot_{a}": (1 - D[f"pct_mvrv_{a}"][i]) / len(act) for a in act if D[f"pct_mvrv_{a}"][i] is not None}, 0.5))
    for on, off in ((0.2, 0.8), (0.3, 0.9), (0.1, 0.7)):
        h = Histeresis(on, off, al_reves=True)
        V.append(("ciclo", f"MVRV percentil: compra < {on:.0%}, vende > {off:.0%} · BTC", False,
                  lambda i, h=h: {"spot_BTC": float(h(D["pct_mvrv_BTC"][i]))}, 0.5))
    for lo in (1.0, 1.2, 1.5):
        for hi in (2.5, 3.0, 3.5):
            h = Histeresis(lo, hi, al_reves=True)
            V.append(("ciclo", f"MVRV fijo: compra < {lo}, vende > {hi} · BTC", False,
                      lambda i, h=h: {"spot_BTC": float(h(D["mvrv_BTC"][i]))}, 0.5))
    for lo, hi in ((1.0, 3.0), (1.2, 3.5)):
        V.append(("ciclo", f"MVRV fijo continuo {lo}–{hi} · BTC", False, lambda i, lo=lo, hi=hi: {
            "spot_BTC": min(1, max(0, (hi - D["mvrv_BTC"][i]) / (hi - lo)))} if D["mvrv_BTC"][i] else {}, 0.5))
    for on, off in ((20, 80), (25, 75)):
        h = Histeresis(on, off, al_reves=True)
        V.append(("ciclo", f"miedo/codicia: compra < {on}, vende > {off} · BTC", False,
                  lambda i, h=h: {"spot_BTC": float(h(D["fng"][i]))}, 0.5))
    V.append(("ciclo", "miedo/codicia continuo · BTC", False,
              lambda i: {"spot_BTC": 1 - D["fng"][i] / 100} if D["fng"][i] is not None else {}, 0.5))
    V.append(("ciclo", "MVRV percentil + miedo/codicia (promedio) · BTC", False, lambda i: {
        "spot_BTC": (2 - D["pct_mvrv_BTC"][i] - D["fng"][i] / 100) / 2}
        if D["pct_mvrv_BTC"][i] is not None and D["fng"][i] is not None else {}, 0.5))

    # 3. Renta neutral
    for g, act in grupos.items():
        V.append(("renta", f"siempre activa · {g}", False, lambda i, act=act: {f"carry_{a}": 1 / len(act) for a in act}, 0.5))
    for n in (3, 7, 14):
        for on in (0.05, 0.10, 0.15):
            for ef in (0.5, 2 / 3):
                if ef != 0.5 and (n, on) != (7, 0.10):
                    continue
                hs = {a: Histeresis(on, on / 2) for a in ACTIVOS}
                V.append(("renta", f"media {n} días > {on:.0%} (sale < {on / 2:.1%}) · BTC+ETH"
                          + (" · eficiencia 2/3" if ef != 0.5 else ""), (n, on, ef) == (7, 0.10, 0.5),
                          lambda i, n=n, hs=hs: {f"carry_{a}": float(hs[a](media_fin(D, a, i, n))) / 2 for a in ACTIVOS}, ef))

    # 4. Combinado
    def combinado(senal="promedio_8", act=ACTIVOS, euforia=0.30, tope_ciclo=True, renta="regimen"):
        hs = {a: Histeresis(0.10, 0.05) for a in act}

        def obj(i):
            w = {}
            for a in act:
                parte = 1 / len(act)
                e = sen[a][senal][i] or 0
                if tope_ciclo and (D[f"pct_mvrv_{a}"][i] or 0) > 0.9:
                    e = min(e, 0.5)
                f7 = media_fin(D, a, i, 7)
                cubierto = e / 2 if euforia and f7 is not None and f7 > euforia else 0.0
                activa = renta == "siempre" or (renta == "regimen" and hs[a](f7))
                libre = (1 - e) if activa else 0.0
                w[f"spot_{a}"] = (e - cubierto) * parte
                w[f"carry_{a}"] = (cubierto + libre) * parte
            return w
        return obj
    V.append(("combinado", "principal: promedio_8 · BTC+ETH · euforia 30% · tope MVRV · renta por régimen", True, combinado(), 0.5))
    V.append(("combinado", "sin tope MVRV", False, combinado(tope_ciclo=False), 0.5))
    V.append(("combinado", "sin freno de euforia", False, combinado(euforia=None), 0.5))
    V.append(("combinado", "euforia 20%", False, combinado(euforia=0.20), 0.5))
    V.append(("combinado", "renta siempre activa en la plata libre", False, combinado(renta="siempre"), 0.5))
    V.append(("combinado", "sin renta (plata libre en caja)", False, combinado(renta=None), 0.5))
    V.append(("combinado", "solo BTC", False, combinado(act=("BTC",)), 0.5))
    V.append(("combinado", "señal sobre_media_100", False, combinado(senal="sobre_media_100"), 0.5))
    return V


# ------------------------------------------------------------------------------------------------ reporte
def pct(x):
    return f"{x:+.1%}".replace(".", ",")


def main():
    D = cargar()
    hoy = dt.date.today().isoformat()
    filas, principales = [], []
    for bolsillo, nombre, principal, obj, ef in variantes(D):
        curva, ops, expo = simular(D, obj, ef)
        p_dis = "diseño_renta" if bolsillo == "renta" else "diseño"
        md, me = metricas(D, curva, ops, expo, p_dis), metricas(D, curva, ops, expo, "examen")
        pasa = all(m["cagr"] >= VARA and m["cagr_sin_mejor_mes"] >= VARA for m in (md, me))
        fila = {"bolsillo": bolsillo, "variante": nombre, "principal": principal, "pasa": pasa}
        for etiqueta, m in (("dis", md), ("exa", me)):
            for k in ("cagr", "cagr_sin_mejor_mes", "max_caida", "sharpe", "peor_mes", "meses_pos", "ops_ano", "expo"):
                fila[f"{etiqueta}_{k}"] = round(m[k], 4)
        filas.append(fila)
        if principal or bolsillo == "referencia":
            principales.append((bolsillo, nombre, md, me, pasa))
        print(f"{bolsillo:10s} {nombre[:60]:60s} diseño {pct(md['cagr']):>7s} caída {pct(md['max_caida']):>7s} · "
              f"examen {pct(me['cagr']):>7s} sin mejor mes {pct(me['cagr_sin_mejor_mes']):>7s} caída "
              f"{pct(me['max_caida']):>7s} ops/año {me['ops_ano']:5.1f}{'  PASA' if pasa else ''}", flush=True)

    os.makedirs(os.path.join(RAIZ, "reportes"), exist_ok=True)
    with open(os.path.join(RAIZ, "reportes", f"fase1-{hoy}-variantes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)

    L = [f"# Fase 1 · evaluación ex-post en dólares ({hoy})", "",
         f"Diseño: {PERIODOS['diseño'][0]} a {PERIODOS['diseño'][1]} (renta neutral desde {PERIODOS['diseño_renta'][0]}). "
         f"Examen: desde {PERIODOS['examen'][0]} hasta {D['fechas'][-1]}. Vara: {VARA:.0%} anual en USD. "
         "Pasa = gana la vara en diseño y examen, también sin su mejor mes.", "",
         "## Versiones principales y referencias", "",
         "| Bolsillo | Versión | Diseño: anual | Diseño: peor caída | Examen: anual | Examen sin mejor mes | "
         "Examen: peor caída | Operaciones/año | Exposición media | Pasa |", "|---|---|---|---|---|---|---|---|---|---|"]
    for b, nombre, md, me, pasa in principales:
        L.append(f"| {b} | {nombre} | {pct(md['cagr'])} | {pct(md['max_caida'])} | {pct(me['cagr'])} | "
                 f"{pct(me['cagr_sin_mejor_mes'])} | {pct(me['max_caida'])} | {me['ops_ano']:.1f} | {me['expo']:.0%} | "
                 f"{'sí' if pasa else 'no'} |")
    L += ["", "## Año por año (versiones principales)", ""]
    anos = sorted({a for _b, _n, md, me, _p in principales for a in list(md["anos"]) + list(me["anos"])})
    L.append("| Versión | " + " | ".join(anos) + " |")
    L.append("|---|" + "---|" * len(anos))
    for b, nombre, md, me, _p in principales:
        r = {**md["anos"], **me["anos"]}
        L.append(f"| {b}: {nombre[:40]} | " + " | ".join(pct(r[a]) if a in r else "" for a in anos) + " |")
    L += ["", "## Sensibilidad: cuántas variantes pasan", ""]
    L.append("| Bolsillo | Variantes | Examen > vara | Pasan (diseño y examen, sin mejor mes) | Examen: mediana anual |")
    L.append("|---|---|---|---|---|")
    for b in ("tendencia", "ciclo", "renta", "combinado"):
        fb = [x for x in filas if x["bolsillo"] == b]
        L.append(f"| {b} | {len(fb)} | {sum(x['exa_cagr'] >= VARA for x in fb)} | {sum(x['pasa'] for x in fb)} | "
                 f"{pct(statistics.median(x['exa_cagr'] for x in fb))} |")
    with open(os.path.join(RAIZ, "reportes", f"fase1-{hoy}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"\nreportes/fase1-{hoy}.md", flush=True)


if __name__ == "__main__":
    sys.exit(main())

"""Práctica sin dinero: una revisión diaria (7:10 pm de Colombia = 00:10 UTC), dos libros simulados y un libro "ideal".
Desde el 16 nov 2026 hay un tercer libro de observación, "adaptativa" (bot/adaptativa.py), que no toca a los otros.
Etapa 2 desde el 16 nov 2026: los tres libros arrancan con $100 con el cierre del 15 nov; la etapa 1 quedó archivada en
datos/paper_etapa1 y reportes/diario_etapa1. Corre en GitHub Actions (.github/workflows/revision-diaria.yml).
  python -m bot correr     → revisa, opera en simulación si toca y actualiza informe.html
  python -m bot reporte    → solo vuelve a escribir el informe (sin operar)
  python -m bot verificar  → revisa la compuerta B (¿ya se puede pasar a dinero real?)
Repetible: si no hay un cierre nuevo ni nada distinto que contar, otra revisión el mismo día no cambia ningún archivo.
Las señales salen de herramientas/estudio.py con la historia completa de datos/: son las mismas del estudio.
Fuentes de datos (las mismas en el PC y en GitHub): bot/fuentes.py. Necesita red (sandbox de Claude desactivado).
"""
import csv
import datetime as dt
import json
import math
import os
import sys
import traceback

from bot import config as C

sys.path.insert(0, os.path.join(C.RAIZ, "herramientas"))
import estudio as E  # noqa: E402
from bot import fuentes as F  # noqa: E402

COT = dt.timezone(dt.timedelta(hours=-5))
ESTADO = os.path.join(C.CARPETA, "estado.json")
DIARIO = os.path.join(C.CARPETA, "diario.csv")
IDEAL = os.path.join(C.CARPETA, "ideal.csv")
OPERACIONES = os.path.join(C.CARPETA, "operaciones.csv")
ERRORES = os.path.join(C.CARPETA, "errores.log")
_RELOJ = None  # solo para pruebas y repeticiones: fija la hora "actual" (UTC)


def ahora_utc():
    return _RELOJ or dt.datetime.now(dt.UTC)


def ahora_cot():
    return ahora_utc().astimezone(COT)


# ------------------------------------------------------------------------------------------------- datos
def actualizar_velas(ahora):
    for a in C.ACTIVOS:
        F.actualizar_spot(a, ahora)


def velas():
    """{activo: {"fechas": [...], "cierre": [...], "maximo": [...]}} desde los CSV del estudio."""
    salida = {}
    for a in C.ACTIVOS:
        filas = E._csv(f"velas_spot_{a}USDT_1d.csv")
        salida[a] = {"fechas": [E._dia(int(r[0])) for r in filas], "cierre": [float(r[4]) for r in filas],
                     "maximo": [float(r[2]) for r in filas]}
    return salida


def revisar_datos(V, esperado):
    """Lista de problemas en los datos (vacía si todo está bien)."""
    problemas = []
    f_btc, f_eth = V["BTC"]["fechas"], V["ETH"]["fechas"]
    if f_btc != f_eth:
        problemas.append("Las fechas de BTC y ETH no coinciden.")
    for a in C.ACTIVOS:
        f, c = V[a]["fechas"], V[a]["cierre"]
        if f[-1] < esperado:
            problemas.append(f"Binance aún no entrega el cierre del {esperado} de {a} (último: {f[-1]}).")
        saltos = [f[i] for i in range(len(f) - 400, len(f)) if E._mas(f[i - 1], 1) != f[i]]
        if saltos:
            problemas.append(f"Faltan días en los precios de {a} (cerca de {saltos[0]}).")
        raros = [f[i] for i in range(len(c) - 400, len(c)) if c[i] <= 0 or abs(c[i] / c[i - 1] - 1) > 0.6]
        if raros:
            problemas.append(f"Precio raro de {a} el {raros[0]} (cambio de más de 60% en un día).")
    return problemas


def cotizacion():
    return F.cotizacion_spot(C.ACTIVOS)


def senales(V):
    """{activo: {fecha: promedio de 8 señales}} con la misma función del estudio."""
    return {a: dict(zip(V[a]["fechas"], E.senales_tendencia(V[a]["cierre"])["promedio_8"])) for a in C.ACTIVOS}


def objetivo(libro, s):
    if libro == "tendencia":
        return {a: (s[a] or 0.0) / len(C.ACTIVOS) for a in C.ACTIVOS}
    return {a: 1 / len(C.ACTIVOS) for a in C.ACTIVOS}


# ------------------------------------------------------------------------------------------------ libros
def libro_nuevo():
    return {"usdt": C.CAPITAL, **{a: 0.0 for a in C.ACTIVOS}, "ajustes": 0, "inicial": False}


def valor(L, p):
    return L["usdt"] + sum(L[a] * p[a] for a in C.ACTIVOS)


def pesos(L, p):
    v = valor(L, p)
    return {a: L[a] * p[a] / v for a in C.ACTIVOS}


def necesita_ajuste(actual, obj):
    """La misma regla del estudio: algún peso cambia ≥ BANDA, o una posición abre o cierra."""
    return any(abs(obj[a] - actual[a]) >= C.BANDA or (obj[a] > 1e-9) != (actual[a] > 1e-9) for a in C.ACTIVOS)


def paso_ideal(L, obj, p):
    """Como estudio.simular: costo COSTO_IDEAL sobre lo que se mueve, cantidades exactas, sin mínimos."""
    actual = pesos(L, p)
    if not necesita_ajuste(actual, obj):
        return False
    v = valor(L, p)
    v -= v * sum(abs(obj[a] - actual[a]) for a in C.ACTIVOS) * C.COSTO_IDEAL
    for a in C.ACTIVOS:
        L[a] = obj[a] * v / p[a]
    L["usdt"] = v * (1 - sum(obj.values()))
    _contar(L)
    return True


def paso_paper(L, obj, cot):
    """Como Binance: vende al bid y compra al ask, comisión 0,1%, pasos de cantidad y orden mínima de $5."""
    medio = {a: sum(cot[a]) / 2 for a in C.ACTIVOS}
    actual = pesos(L, medio)
    if not necesita_ajuste(actual, obj):
        return []
    v = valor(L, medio)
    ops = []
    for lado in ("venta", "compra"):
        for a in C.ACTIVOS:
            dif = obj[a] * v - L[a] * medio[a]
            if lado == "venta" and dif < 0:
                precio = cot[a][0]
                cant = math.floor(min(L[a], -dif / precio) / C.PASO[a] + 1e-9) * C.PASO[a]
            elif lado == "compra" and dif > 0:
                precio = cot[a][1]
                cant = math.floor(min(dif, L["usdt"]) / precio / C.PASO[a] + 1e-9) * C.PASO[a]
            else:
                continue
            monto = cant * precio
            if monto < C.MIN_ORDEN:
                if monto > 0.01:
                    ops.append({"activo": a, "lado": lado, "cantidad": 0, "precio": precio, "monto": monto,
                                "comision": 0, "nota": "omitida: menor que la orden mínima de $5"})
                continue
            if lado == "venta":
                L[a] -= cant
                L["usdt"] += monto * (1 - C.COMISION)
            else:
                L[a] += cant * (1 - C.COMISION)
                L["usdt"] -= monto
            ops.append({"activo": a, "lado": lado, "cantidad": cant, "precio": precio, "monto": monto,
                        "comision": monto * C.COMISION, "nota": ""})
    if any(o["cantidad"] for o in ops):
        _contar(L)
    return ops


def _contar(L):
    if L["inicial"]:
        L["ajustes"] += 1
    L["inicial"] = True


# ------------------------------------------------------------------------------------------------ archivos
def cargar_estado():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    return None


def guardar_estado(st):
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)
    os.replace(tmp, ESTADO)


def anexar(ruta, fila):
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fila))
        if nuevo:
            w.writeheader()
        w.writerow(fila)


def leer(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def anotar_error(texto):
    with open(ERRORES, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"--- {ahora_cot():%Y-%m-%d %H:%M} (Colombia)\n{texto}\n")


def _huella(st):
    """El estado sin la hora de la última revisión: si no cambia, la revisión no tiene nada nuevo que guardar."""
    return None if st is None else json.dumps({k: v for k, v in st.items() if k != "ultima_corrida"}, sort_keys=True)


# ------------------------------------------------------------------------------------------------- ciclo
def correr(ahora=None, cot=None, cotp=None):
    """Una revisión. `ahora`, `cot` y `cotp` (cotizaciones del contado y del perpetuo) solo se pasan en pruebas y
    repeticiones; normalmente se toman en vivo."""
    global _RELOJ
    _RELOJ = ahora
    os.makedirs(C.CARPETA, exist_ok=True)
    ahora = ahora_utc()
    esperado = (ahora.date() - dt.timedelta(days=1)).isoformat()  # último día UTC ya cerrado
    actualizar_velas(ahora)
    V = velas()
    problemas = revisar_datos(V, esperado)
    S = senales(V)
    st = cargar_estado()
    huella = _huella(st)
    fechas = V["BTC"]["fechas"]
    cierre = {a: dict(zip(fechas, V[a]["cierre"])) for a in C.ACTIVOS}
    D = fechas[-1]  # último cierre disponible
    if st is None:
        st = {"etapa": C.ETAPA, "inicio": C.INICIO, "creado": ahora.isoformat(), "primer_dia": D, "ultimo_ideal": None,
              "ultimo_paper": None, "libros": {k: libro_nuevo() for k in C.LIBROS},
              "ideal": {k: libro_nuevo() for k in C.LIBROS}}

    # Libro ideal: decide cada día al cierre, aunque el PC haya estado apagado.
    pendientes = [f for f in fechas if f >= st["primer_dia"] and (st["ultimo_ideal"] is None or f > st["ultimo_ideal"])]
    for f in pendientes:
        p = {a: cierre[a][f] for a in C.ACTIVOS}
        s = {a: S[a][f] for a in C.ACTIVOS}
        fila = {"fecha": f, **{f"senal_{a}": s[a] for a in C.ACTIVOS}, **{f"cierre_{a}": p[a] for a in C.ACTIVOS}}
        for k in C.LIBROS:
            opero = paso_ideal(st["ideal"][k], objetivo(k, s), p)
            fila[f"opero_{k}"] = int(opero)
            fila[f"valor_{k}"] = round(valor(st["ideal"][k], p), 4)
        anexar(IDEAL, fila)
        st["ultimo_ideal"] = f

    # Libros de práctica: deciden una vez por cada cierre nuevo, cuando el bot corre.
    nuevo_dia = (st["ultimo_paper"] is None or D > st["ultimo_paper"]) and not any("aún no entrega" in x for x in problemas)
    hoy = None
    if nuevo_dia:
        cot = cot or cotizacion()
        st["cotizacion"] = {"hora_utc": ahora.isoformat(), **{a: list(cot[a]) for a in C.ACTIVOS}}
        objetivo_hora = dt.datetime.fromisoformat(E._mas(D, 1) + "T00:10:00+00:00")
        atraso_h = max(0.0, (ahora - objetivo_hora).total_seconds() / 3600)
        omitidos = 0 if st["ultimo_paper"] is None else (dt.date.fromisoformat(D) - dt.date.fromisoformat(st["ultimo_paper"])).days - 1
        s = {a: S[a][D] for a in C.ACTIVOS}
        medio = {a: sum(cot[a]) / 2 for a in C.ACTIVOS}
        p_cierre = {a: cierre[a][D] for a in C.ACTIVOS}
        hoy = {"fecha_cierre": D, "hora": ahora_cot().strftime("%Y-%m-%d %H:%M"), "atraso_h": round(atraso_h, 2),
               "dias_sin_revision": omitidos, **{f"senal_{a}": s[a] for a in C.ACTIVOS},
               **{f"cierre_{a}": p_cierre[a] for a in C.ACTIVOS}, **{f"precio_{a}": round(medio[a], 2) for a in C.ACTIVOS}}
        for k in C.LIBROS:
            ops = paso_paper(st["libros"][k], objetivo(k, s), cot)
            for o in ops:
                anexar(OPERACIONES, {"hora": hoy["hora"], "fecha_cierre": D, "libro": k, **{x: (round(y, 8) if isinstance(y, float) else y) for x, y in o.items()}})
            hoy[f"opero_{k}"] = int(any(o["cantidad"] for o in ops))
            hoy[f"valor_{k}"] = round(valor(st["libros"][k], medio), 4)
            hoy[f"valor_cierre_{k}"] = round(valor(st["libros"][k], p_cierre), 4)
            hoy[f"ideal_{k}"] = round(valor(st["ideal"][k], p_cierre), 4)
            hoy[f"pesos_{k}"] = json.dumps({a: round(w, 4) for a, w in pesos(st["libros"][k], medio).items()})
        hoy["problemas"] = " | ".join(problemas)
        anexar(DIARIO, hoy)
        st["ultimo_paper"] = D
    st["problemas"] = problemas
    cambio = _huella(st) != huella
    if cambio:
        st["ultima_corrida"] = ahora_cot().strftime("%Y-%m-%d %H:%M")
        guardar_estado(st)

    # Tercer libro "adaptativa" (solo observación): va después de guardar los otros dos y nunca los afecta.
    try:
        from bot import adaptativa
        cambio = adaptativa.correr(V, ahora, cot, cotp) or cambio  # anota sus problemas en adaptativa_errores.log
    except Exception:
        cambio = True
        with open(os.path.join(C.CARPETA, "adaptativa_errores.log"), "a", encoding="utf-8", newline="\n") as f:
            f.write(f"--- {ahora_cot():%Y-%m-%d %H:%M} (Colombia)\n{traceback.format_exc()}\n")

    from bot import informe
    if not cambio and informe.al_dia():  # nada nuevo: no se reescribe ningún archivo
        return informe.escribir(st, V, S, guardar=False)
    return informe.escribir(st, V, S)


def main(args):
    os.makedirs(C.CARPETA, exist_ok=True)
    if sys.stdout is None:  # pythonw (tarea programada de Windows): sin consola
        sys.stdout = sys.stderr = open(os.path.join(C.CARPETA, "salida.log"), "a", encoding="utf-8")
    orden = args[0] if args else "correr"
    try:
        if orden == "correr":
            r = correr()
            print(f"{ahora_cot():%Y-%m-%d %H:%M} {r['titulo']} · {r['texto']}", flush=True)
        elif orden == "reporte":
            from bot import informe
            V = velas()
            print(informe.escribir(cargar_estado(), V, senales(V))["titulo"])
        elif orden == "verificar":
            from bot import reporte
            st = cargar_estado()
            V = velas()
            r = reporte.calcular(st, V, senales(V))
            print("\n".join(f"{'✓' if ok else '✗'} {texto}" for ok, texto in r["compuerta"]))
            print("LISTO PARA DINERO REAL" if r["listo"] else "TODAVÍA NO")
        else:
            print(__doc__)
    except Exception:
        anotar_error(traceback.format_exc())
        try:  # deja el error a la vista en informe.html
            from bot import informe
            informe.reconstruir(traceback.format_exc().strip().splitlines()[-1])
        except Exception:
            anotar_error(traceback.format_exc())
        raise

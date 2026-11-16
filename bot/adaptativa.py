"""Tercer libro de práctica "adaptativa" (alza + baja), Estrategia 3 de BITACORA.md. Solo de observación: no cuenta
para la compuerta B y no toca los libros "tendencia" y "mantener" (ni sus archivos).

- Lado al alza: los mismos objetivos que "tendencia" (8 señales, banda de 10%), ejecutados como el libro de tendencia
  (contado de Binance: bid/ask, comisión 0,1%, pasos de cantidad, orden mínima de $5).
- Lado a la baja: la regla de config.ADAPTATIVA (versión elegida por herramientas/estudio3.py), con el precio real del
  perpetuo de Hyperliquid y su financiación real (desde la etapa 2, 16 nov 2026; antes, Binance USD-M), comisión 0,05%
  por lado, orden mínima de $10 para abrir, cantidad fija mientras está abierto y sin apalancamiento (largo + nocional
  corto ≤ 100% del libro). En Hyperliquid la financiación se cobra CADA HORA: la práctica abona o descuenta cada cobro
  horario (cantidad × precio de esa hora × tasa) desde que el corto está abierto; el ideal suma los 24 cobros del día
  sobre el nocional del cierre anterior (la convención del estudio, que con Binance sumaba 3 cobros de 8 h).
- Libro "ideal": lo mismo con precios de cierre y los costos del estudio (contado 0,15%, perpetuo 0,10%), procesando
  cada cierre en orden; sirve para medir cuánto se aleja la práctica de la simulación.

Estado en datos/paper/adaptativa.json (regla por activo con su cierre más bajo desde la entrada y su freno ATR, libro
de práctica, libro ideal). Filas en adaptativa_diario.csv (una por revisión), adaptativa_ideal.csv (una por cierre),
adaptativa_operaciones.csv. Problemas en adaptativa_errores.log (aparte de errores.log, que cuenta para la compuerta B).
"""
import collections
import csv
import datetime as dt
import json
import math
import os
import traceback

from bot import config as C
from bot import principal as P

E, F = P.E, P.F
K = C.ADAPTATIVA
R_ = K["regla"]
ESTADO = os.path.join(C.CARPETA, "adaptativa.json")
DIARIO = os.path.join(C.CARPETA, "adaptativa_diario.csv")
IDEAL = os.path.join(C.CARPETA, "adaptativa_ideal.csv")
OPERACIONES = os.path.join(C.CARPETA, "adaptativa_operaciones.csv")
ERRORES = os.path.join(C.CARPETA, "adaptativa_errores.log")
A = C.ACTIVOS
SALIDA_SENAL = 3 / 8

CAMPOS_DIARIO = (["fecha_cierre", "hora", "atraso_h", "dias_sin_revision"] + [f"senal_{a}" for a in A]
                 + [f"cierre_{a}" for a in A] + [f"perp_cierre_{a}" for a in A] + [f"precio_{a}" for a in A]
                 + [f"perp_{a}" for a in A] + ["opero", "valor", "valor_cierre", "ideal", "pesos", "cortos", "problemas"])
CAMPOS_IDEAL = (["fecha"] + [f"senal_{a}" for a in A] + [f"cierre_{a}" for a in A] + [f"perp_{a}" for a in A]
                + ["opero", "valor"] + [f"corto_{a}" for a in A])
CAMPOS_OPS = ["hora", "fecha_cierre", "libro", "activo", "lado", "cantidad", "precio", "monto", "comision", "nota"]


# ------------------------------------------------------------------------------------------------- datos
def actualizar_datos(ahora):
    """Velas diarias del perpetuo de Hyperliquid y su financiación horaria (bot/fuentes.py). Devuelve los problemas."""
    problemas = []
    for a in A:
        try:
            F.actualizar_perp(a, ahora)
        except Exception as e:  # sin red o Hyperliquid caído: el libro espera a la próxima revisión
            problemas.append(f"No se pudieron bajar los datos del perpetuo de {a} ({str(e)[:120]}).")
    return problemas


def cotizacion_perp():
    """{activo: (bid, ask)} del perpetuo de Hyperliquid."""
    return F.cotizacion_perp(A)


def _ms_dia(f):
    return int(dt.datetime.fromisoformat(f + "T00:00:00+00:00").timestamp() * 1000)


def atr_wilder(h, l, c, n=14):
    tr = [None] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    out = [None] * len(c)
    if len(c) > n:
        out[n] = sum(tr[1:n + 1]) / n
        for i in range(n + 1, len(c)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def series(V):
    """Series diarias alineadas al calendario del contado (V de principal.velas()), igual que estudio.cargar()."""
    fechas = V["BTC"]["fechas"]
    X = {"fechas": fechas, "idx": {f: i for i, f in enumerate(fechas)}, "n": len(fechas)}
    for a in A:
        hl = {E._dia(int(r[0])): (float(r[2]), float(r[3])) for r in E._csv(f"velas_spot_{a}USDT_1d.csv")}
        perp = {E._dia(int(r[0])): float(r[4]) for r in E._csv(os.path.basename(F.ruta_velas_perp(a)))}
        fin, nfin, eventos = collections.defaultdict(float), collections.defaultdict(int), []
        for r in E._csv(os.path.basename(F.ruta_financiacion(a))):
            ms, tasa = int(r[0]), float(r[1])
            d = E._dia(ms // 3_600_000 * 3_600_000 - 1)  # el cobro de las 00:00 de D+1 es del día D (de 01:00 a 00:00)
            fin[d] += tasa
            nfin[d] += 1
            eventos.append((ms, tasa, float(r[2]) if len(r) > 2 and r[2] else None))
        c = V[a]["cierre"]
        p = [perp.get(f) for f in fechas]
        hay = [i > 0 and p[i] is not None and p[i - 1] is not None and f in fin for i, f in enumerate(fechas)]
        sen = E.senales_tendencia(c)
        X[a] = {"P": c, "perp": p, "hay": hay, "fin": [fin.get(f, 0.0) for f in fechas],
                "nfin": [nfin.get(f, 0) for f in fechas], "eventos": eventos, "s8": sen["promedio_8"],
                "fin_hasta": max((e[0] for e in eventos), default=0),
                "atr": atr_wilder([hl[f][0] for f in fechas], [hl[f][1] for f in fechas], c)}
        if a == "BTC":
            X["bajo200"] = [x == 0.0 for x in sen["sobre_media_200"]]
    return X


def completo(X, i):
    """¿Ya están el cierre del perpetuo y todos los cobros de financiación del día i (el último es el de las 00:00 UTC
    del día siguiente)?"""
    fin_dia = _ms_dia(X["fechas"][i]) + 86_400_000
    return all(X[a]["perp"][i] is not None and X[a]["nfin"][i] > 0 and X[a]["fin_hasta"] >= fin_dia for a in A)


def fin30(X, a, i):
    """Como estudio.media_fin(D, a, i, 30)."""
    if i < 30 or not all(X[a]["hay"][i - 29:i + 1]):
        return None
    return sum(X[a]["fin"][i - 29:i + 1]) / 30 * 365


# ------------------------------------------------------------------------------------------------- regla
def regla_nueva():
    return {"abierto": False, "eid": 0, "entrada": None, "precio_entrada": None, "bajo": None, "stop": None,
            "salida": None, "motivo": None}


def paso_regla(g, X, a, i):
    """Actualiza la regla del corto de un activo con el cierre i (en orden). Misma lógica que estudio3.Pre.regla."""
    P_, s = X[a]["P"], X[a]["s8"][i]
    f, atr = X["fechas"][i], X[a]["atr"][i]
    if g["abierto"]:
        g["bajo"] = min(g["bajo"], P_[i])
        g["stop"] = g["bajo"] + R_["atr"] * atr if R_["atr"] is not None and atr is not None else None
        N = R_["cierre"]
        motivo = None
        if i >= N and P_[i] > max(P_[i - N:i]):
            motivo = f"cerró sobre el máximo de los {N} cierres anteriores"
        elif s is not None and s >= SALIDA_SENAL - 1e-9:
            motivo = f"volvió a {round(s * 8)} de 8 señales al alza"
        elif g["stop"] is not None and P_[i] > g["stop"]:
            motivo = "tocó el freno (cierre más bajo desde la entrada + ATR)"
        if motivo:
            g.update(abierto=False, salida=f, motivo=motivo)
            return "cierra"
        return None
    N = R_["ruptura"]
    f30 = fin30(X, a, i)
    if (X[a]["hay"][i] and i >= N and P_[i] < min(P_[i - N:i]) and s is not None and s <= R_["senales"] / 8 + 1e-9
            and (not R_["f200"] or X["bajo200"][i]) and (not R_["ffin"] or (f30 is not None and f30 >= 0))):
        stop = P_[i] + R_["atr"] * atr if R_["atr"] is not None and atr is not None else None
        g.update(abierto=True, eid=g["eid"] + 1, entrada=f, precio_entrada=P_[i], bajo=P_[i], stop=stop, salida=None,
                 motivo=None)
        return "abre"
    return None


# ------------------------------------------------------------------------------------------------- libros
def libro_nuevo():
    return {"usdt": C.CAPITAL, **{a: 0.0 for a in A}, "ajustes": 0, "inicial": False, "cortos": {},
            "hecho": {a: 0 for a in A}, "cortos_abiertos": 0}


def no_realizado(L, pp):
    return sum(k["cant"] * (k["entrada"] - pp[a]) for a, k in L["cortos"].items())


def nocional(L, pp):
    return sum(k["cant"] * pp[a] for a, k in L["cortos"].items())


def valor(L, ps, pp):
    return L["usdt"] + sum(L[a] * ps[a] for a in A) + no_realizado(L, pp)


def objetivo_con_tope(s, V, noc):
    """Objetivos de "tendencia"; si largo + nocional corto pasaría de 100% del libro, el largo se escala."""
    obj = P.objetivo("tendencia", s)
    lim = max(0.0, 1 - noc / V) if noc else 1.0
    tot = sum(obj.values())
    if tot > lim + 1e-12:
        obj = {a: w * lim / tot for a, w in obj.items()}
    return obj


def paso_ideal(L, X, i, regla):
    """Un cierre del libro ideal, en el orden del estudio: resultado del corto, cierres/aperturas, lado largo."""
    ps = {a: X[a]["P"][i] for a in A}
    pp = {a: X[a]["perp"][i] for a in A}
    ops = []
    for a, k in L["cortos"].items():  # financiación del día sobre el nocional del cierre anterior
        pago = k["cant"] * k["ref"] * (X[a]["fin"][i] if X[a]["hay"][i] else 0.0)
        L["usdt"] += pago
        k["fin"] += pago
        k["ref"] = pp[a]
    for a in A:
        g, k = regla[a], L["cortos"].get(a)
        if k and (not g["abierto"] or g["eid"] != k["eid"]):
            fee = k["cant"] * pp[a] * K["costo_ideal_corto"]
            L["usdt"] += k["cant"] * (k["entrada"] - pp[a]) - fee
            ops.append(("cierra", a, k["cant"], pp[a], fee))
            del L["cortos"][a]
        if g["abierto"] and g["eid"] != L["hecho"][a] and a not in L["cortos"] and X[a]["hay"][i]:
            L["hecho"][a] = g["eid"]
            V = valor(L, ps, pp)
            tam = min(R_["tam"], 1 - (sum(L[b] * ps[b] for b in A) + nocional(L, pp)) / V)
            if tam > 1e-6:
                fee = tam * V * K["costo_ideal_corto"]
                cant = tam * (V - fee) / pp[a]
                L["usdt"] -= fee
                L["cortos"][a] = {"cant": cant, "entrada": pp[a], "eid": g["eid"], "fecha": X["fechas"][i], "fin": 0.0,
                                  "com": fee, "ref": pp[a]}
                L["cortos_abiertos"] += 1
                ops.append(("abre", a, cant, pp[a], fee))
    V = valor(L, ps, pp)
    obj = objetivo_con_tope({a: X[a]["s8"][i] for a in A}, V, nocional(L, pp))
    actual = {a: L[a] * ps[a] / V for a in A}
    if P.necesita_ajuste(actual, obj):
        V -= V * sum(abs(obj[a] - actual[a]) for a in A) * C.COSTO_IDEAL
        for a in A:
            L[a] = obj[a] * V / ps[a]
        L["usdt"] = V - sum(obj[a] * V for a in A) - no_realizado(L, pp)
        P._contar(L)
        ops.append(("largo",))
    return ops


def paso_paper(L, X, i, regla, cot, cotp, ahora_ms):
    """La revisión del día en la práctica: financiación cobrada/pagada desde la última revisión, cortos según el
    estado de la regla, y el lado largo como el libro de tendencia (con el tope sin apalancamiento)."""
    ops = []
    ms = {a: sum(cot[a]) / 2 for a in A}
    mp = {a: sum(cotp[a]) / 2 for a in A}
    for a, k in L["cortos"].items():
        for t, tasa, marca in X[a]["eventos"]:
            if k["fin_ms"] < t <= ahora_ms:
                pago = k["cant"] * (marca or mp[a]) * tasa
                L["usdt"] += pago
                k["fin"] += pago
                k["n_fin"] += 1
                k["fin_ms"] = t
    for a in A:
        g, k = regla[a], L["cortos"].get(a)
        if k and (not g["abierto"] or g["eid"] != k["eid"]):
            precio = cotp[a][1]  # recompra al ask
            monto = k["cant"] * precio
            fee = monto * K["comision_corto"]
            res = k["cant"] * (k["entrada"] - precio)
            L["usdt"] += res - fee
            ops.append({"activo": a, "lado": "cierra corto", "cantidad": k["cant"], "precio": precio, "monto": monto,
                        "comision": fee, "nota": f"resultado {res + k['fin'] - k['com'] - fee:+.2f} USD con financiación y "
                                                 f"comisiones; {g['motivo'] or 'nueva entrada de la regla'}"})
            del L["cortos"][a]
        if g["abierto"] and g["eid"] != L["hecho"][a] and a not in L["cortos"]:
            L["hecho"][a] = g["eid"]
            V = valor(L, ms, mp)
            tam = min(R_["tam"], 1 - (sum(L[b] * ms[b] for b in A) + nocional(L, mp)) / V)
            precio = cotp[a][0]  # vende al bid
            cant = round(math.floor(max(0.0, tam) * V / precio / K["paso_corto"][a] + 1e-9) * K["paso_corto"][a], 8)
            monto = cant * precio
            if monto < K["min_orden_corto"]:
                ops.append({"activo": a, "lado": "abre corto", "cantidad": 0, "precio": precio, "monto": monto,
                            "comision": 0, "nota": f"omitida: menor que la orden mínima de ${K['min_orden_corto']:.0f}"})
                continue
            fee = monto * K["comision_corto"]
            L["usdt"] -= fee
            L["cortos"][a] = {"cant": cant, "entrada": precio, "eid": g["eid"], "fecha": X["fechas"][i], "fin": 0.0,
                              "n_fin": 0, "com": fee, "fin_ms": ahora_ms, "entrada_regla": g["entrada"]}
            L["cortos_abiertos"] += 1
            ops.append({"activo": a, "lado": "abre corto", "cantidad": cant, "precio": precio, "monto": monto,
                        "comision": fee, "nota": "" if g["entrada"] == X["fechas"][i] else
                        f"la regla abrió con el cierre del {g['entrada']}; se abre hoy"})
    ops += paso_largo(L, objetivo_con_tope({a: X[a]["s8"][i] for a in A}, valor(L, ms, mp), nocional(L, mp)),
                      cot, no_realizado(L, mp), nocional(L, mp))
    return ops


def paso_largo(L, obj, cot, extra, reservado):
    """principal.paso_paper con dos cambios: el valor del libro incluye el resultado del corto, y las compras no usan
    la garantía de los cortos (sin apalancamiento)."""
    medio = {a: sum(cot[a]) / 2 for a in A}
    v = L["usdt"] + sum(L[a] * medio[a] for a in A) + extra
    actual = {a: L[a] * medio[a] / v for a in A}
    if not P.necesita_ajuste(actual, obj):
        return []
    ops = []
    for lado in ("venta", "compra"):
        for a in A:
            dif = obj[a] * v - L[a] * medio[a]
            if lado == "venta" and dif < 0:
                precio = cot[a][0]
                cant = math.floor(min(L[a], -dif / precio) / C.PASO[a] + 1e-9) * C.PASO[a]
            elif lado == "compra" and dif > 0:
                precio = cot[a][1]
                libre = max(0.0, L["usdt"] + extra - reservado)
                cant = math.floor(min(dif, libre) / precio / C.PASO[a] + 1e-9) * C.PASO[a]
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
        P._contar(L)
    return ops


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


def anexar(ruta, campos, fila):
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        if nuevo:
            w.writeheader()
        w.writerow({k: fila.get(k, "") for k in campos})


def anotar(texto):
    with open(ERRORES, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"--- {P.ahora_cot():%Y-%m-%d %H:%M} (Colombia)\n{texto}\n")


def nuevo_estado(X, i0, ahora):
    """Libro nuevo que arranca con el cierre i0. La regla se pone al día con toda la historia anterior (los mismos
    pasos que el estudio), para que el corto que la regla tenga abierto hoy se refleje desde el primer día."""
    regla = {a: regla_nueva() for a in A}
    for i in range(i0):
        for a in A:
            paso_regla(regla[a], X, a, i)
    return {"creado": ahora.isoformat(), "version": K["version"], "parametros": R_, "primer_dia": X["fechas"][i0],
            "ultimo_regla": X["fechas"][i0 - 1], "ultimo_ideal": None, "ultimo_paper": None, "regla": regla,
            "libro": libro_nuevo(), "ideal": libro_nuevo(), "problemas": []}


def procesar_cierres(st, X, hasta):
    """Regla e ideal: cada cierre pendiente en orden, hasta el índice `hasta` o el primero sin datos completos."""
    problemas = []
    k = X["idx"][st["ultimo_regla"]] + 1
    while k <= hasta:
        if not completo(X, k):
            problemas.append(f"Aún no están el cierre del perpetuo o la financiación del {X['fechas'][k]}; el libro "
                             "adaptativa lo procesa en la próxima revisión.")
            break
        f = X["fechas"][k]
        for a in A:
            paso_regla(st["regla"][a], X, a, k)
        st["ultimo_regla"] = f
        if f >= st["primer_dia"]:
            ops = paso_ideal(st["ideal"], X, k, st["regla"])
            pp = {a: X[a]["perp"][k] for a in A}
            ps = {a: X[a]["P"][k] for a in A}
            anexar(IDEAL, CAMPOS_IDEAL, {"fecha": f, **{f"senal_{a}": X[a]["s8"][k] for a in A},
                                         **{f"cierre_{a}": ps[a] for a in A}, **{f"perp_{a}": pp[a] for a in A},
                                         "opero": int(bool(ops)), "valor": round(valor(st["ideal"], ps, pp), 4),
                                         **{f"corto_{a}": int(a in st["ideal"]["cortos"]) for a in A}})
            st["ultimo_ideal"] = f
        k += 1
    return problemas


def correr(V, ahora, cot=None, cotp=None):
    """Una revisión del libro adaptativa. V = velas del contado ya actualizadas por principal.correr(); cot = cotización
    del contado si principal ya la pidió en esta revisión; cotp = la del perpetuo (solo en pruebas y repeticiones).
    Nunca lanza errores hacia afuera: los anota aparte. Devuelve True si cambió algo que haya que guardar o contar."""
    try:
        return _correr(V, ahora, cot, cotp)
    except Exception:
        st = cargar_estado()
        error = "Error del libro adaptativa: " + traceback.format_exc().strip().splitlines()[-1]
        if st is not None and st.get("problemas") == [error]:
            return False  # el mismo error que en la revisión anterior: ya está anotado
        anotar(traceback.format_exc())
        if st is not None:
            st["problemas"] = [error]
            guardar_estado(st)
        return True


def _huella(st):
    return None if st is None else json.dumps({k: v for k, v in st.items() if k != "ultima_corrida"}, sort_keys=True)


def _correr(V, ahora, cot, cotp):
    problemas = actualizar_datos(ahora)
    X = series(V)
    D = X["fechas"][-1]
    iD = X["idx"][D]
    st = cargar_estado()
    huella = _huella(st)
    antes = None if st is None else st.get("problemas")
    if st is None:
        if not completo(X, iD):
            texto = "Libro adaptativa sin iniciar: faltan datos del perpetuo del " + D + ". " + " ".join(problemas)
            if not os.path.exists(ERRORES) or texto not in open(ERRORES, encoding="utf-8").read():
                anotar(texto)
                return True
            return False
        st = nuevo_estado(X, iD, ahora)
    problemas += procesar_cierres(st, X, iD)

    if st["ultimo_regla"] == D and (st["ultimo_paper"] is None or D > st["ultimo_paper"]):
        try:
            cot = cot or P.cotizacion()
            cotp = cotp or cotizacion_perp()
            st["cotizacion_perp"] = {"hora_utc": ahora.isoformat(), **{a: list(cotp[a]) for a in A}}
        except Exception as e:
            problemas.append(f"No se pudo leer el precio en vivo ({str(e)[:120]}); el libro adaptativa opera en la "
                             "próxima revisión.")
            cotp = None
        if cotp:
            L = st["libro"]
            hora = P.ahora_cot().strftime("%Y-%m-%d %H:%M")
            ops = paso_paper(L, X, iD, st["regla"], cot, cotp, int(ahora.timestamp() * 1000))
            for o in ops:
                anexar(OPERACIONES, CAMPOS_OPS, {"hora": hora, "fecha_cierre": D, "libro": "adaptativa",
                                                 **{x: (round(y, 8) if isinstance(y, float) else y) for x, y in o.items()}})
            ms = {a: sum(cot[a]) / 2 for a in A}
            mp = {a: sum(cotp[a]) / 2 for a in A}
            ps = {a: X[a]["P"][iD] for a in A}
            pp = {a: X[a]["perp"][iD] for a in A}
            v = valor(L, ms, mp)
            objetivo_hora = dt.datetime.fromisoformat(E._mas(D, 1) + "T00:10:00+00:00")
            cortos = {a: {"cantidad": k["cant"], "precio_entrada": k["entrada"], "desde": k["fecha"],
                          "nocional": round(k["cant"] * mp[a], 4), "precio_hoy": round(mp[a], 2),
                          "resultado_precio": round(k["cant"] * (k["entrada"] - mp[a]), 4),
                          "financiacion": round(k["fin"], 4), "comisiones": round(k["com"], 4),
                          "stop": st["regla"][a]["stop"], "bajo": st["regla"][a]["bajo"]}
                      for a, k in L["cortos"].items()}
            anexar(DIARIO, CAMPOS_DIARIO, {
                "fecha_cierre": D, "hora": hora, "atraso_h": round(max(0.0, (ahora - objetivo_hora).total_seconds() / 3600), 2),
                "dias_sin_revision": 0 if st["ultimo_paper"] is None else
                (dt.date.fromisoformat(D) - dt.date.fromisoformat(st["ultimo_paper"])).days - 1,
                **{f"senal_{a}": X[a]["s8"][iD] for a in A}, **{f"cierre_{a}": ps[a] for a in A},
                **{f"perp_cierre_{a}": pp[a] for a in A}, **{f"precio_{a}": round(ms[a], 2) for a in A},
                **{f"perp_{a}": round(mp[a], 2) for a in A}, "opero": int(any(o["cantidad"] for o in ops)),
                "valor": round(v, 4), "valor_cierre": round(valor(L, ps, pp), 4),
                "ideal": round(valor(st["ideal"], ps, pp), 4),
                "pesos": json.dumps({a: round(L[a] * ms[a] / v, 4) for a in A}),
                "cortos": json.dumps(cortos, ensure_ascii=False), "problemas": " | ".join(problemas)})
            st["ultimo_paper"] = D
    st["problemas"] = problemas
    if _huella(st) == huella:
        return False  # nada nuevo: no se reescribe ningún archivo
    st["ultima_corrida"] = P.ahora_cot().strftime("%Y-%m-%d %H:%M")
    guardar_estado(st)
    if problemas and problemas != antes:
        anotar("\n".join(problemas))
    return True


# ------------------------------------------------------------------------------------------------ resumen
def resumen():
    """Lo que muestra el informe: último valor de la práctica, posiciones, cortos abiertos, diferencia con el ideal."""
    st = cargar_estado()
    if st is None:
        return None
    filas = P.leer(DIARIO)
    if not filas:
        return {"st": st, "valor": None, "problemas": st.get("problemas", []), "veredicto": K["veredicto"]}
    u = filas[-1]
    serie = [float(r["valor"]) for r in filas]
    ops = [o for o in P.leer(OPERACIONES) if o["hora"] == u["hora"]]
    return {"st": st, "filas": filas, "ult": u, "valor": serie[-1], "desde_inicio": serie[-1] / C.CAPITAL - 1,
            "ayer": serie[-1] / serie[-2] - 1 if len(serie) > 1 else 0.0, "pesos": json.loads(u["pesos"]),
            "cortos": json.loads(u["cortos"]), "dif_ideal": (float(u["valor_cierre"]) - float(u["ideal"])) / C.CAPITAL,
            "ops_hoy": ops, "por_fecha": {r["fecha_cierre"]: float(r["valor"]) for r in filas},
            "problemas": st.get("problemas", []), "veredicto": K["veredicto"], "inicio": st["primer_dia"],
            "ajustes": st["libro"]["ajustes"], "ajustes_ideal": st["ideal"]["ajustes"]}

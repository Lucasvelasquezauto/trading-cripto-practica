"""Repite días sintéticos sobre una COPIA del proyecto ya iniciada en la etapa 2 (sin red):
  python prueba_sintetica.py <copia>
Comprueba: un cierre nuevo por revisión, repetir la revisión el mismo día no cambia ningún archivo, ponerse al día
si faltó un día, financiación horaria, cierre de un corto, aviso si Binance no entrega el cierre, compuerta B."""
import csv
import datetime as dt
import hashlib
import json
import os
import sys

RAIZ = os.path.abspath(sys.argv[1])
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)
from bot import adaptativa as AD  # noqa: E402
from bot import config as C  # noqa: E402
from bot import fuentes as F  # noqa: E402
from bot import principal as P  # noqa: E402
from bot import reporte  # noqa: E402

F.actualizar_spot = lambda a, ahora: None  # sin red: los datos sintéticos ya están en los archivos
F.actualizar_perp = lambda a, ahora: None
DIA, HORA = 86_400_000, 3_600_000


def ms(f):
    return int(dt.datetime.fromisoformat(f + "T00:00:00+00:00").timestamp() * 1000)


def anexar(ruta, filas):
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(filas)


def huellas():
    out = {}
    for base in ("datos", "reportes", "."):
        for raiz, _d, archivos in os.walk(base):
            if base == "." and raiz != ".":
                continue
            for n in archivos:
                p = os.path.join(raiz, n)
                if "__pycache__" not in p:
                    out[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


# Precios sintéticos de cierre: BTC sube fuerte el 17 (rompe el máximo de 10 cierres → cierra el corto), ETH baja.
CIERRES = {"2026-11-16": (64100.0, 1800.0), "2026-11-17": (72500.0, 1790.0), "2026-11-18": (73000.0, 1750.0),
           "2026-11-19": (74000.0, 1700.0), "2026-11-20": None}
previo = {"BTC": 65351.05, "ETH": 1835.35}


def agregar(f):
    """Los datos de un día que llegan después de su cierre (velas del contado y del perpetuo, 24 cobros horarios)."""
    c = CIERRES[f]
    for i, a in enumerate(C.ACTIVOS):
        x = c[i]
        anexar(f"datos/velas_spot_{a}USDT_1d.csv", [[ms(f), previo[a], max(x, previo[a]) * 1.01, min(x, previo[a]) * 0.99, x, 1000.0]])
        anexar(F.ruta_velas_perp(a), [[ms(f), previo[a] - 20, max(x, previo[a]), min(x, previo[a]), x - 15, 1000.0]])
        # 24 cobros horarios de 01:00 del día a 00:00 del siguiente, tasa 0,00125% por hora (≈ 11% al año)
        anexar(F.ruta_financiacion(a), [[ms(f) + h * HORA + 40, "0.0000125", round(x - 15, 1)] for h in range(1, 25)])
        previo[a] = x


def revisar(cuando, cot, cotp, nota):
    antes = huellas()
    r = P.correr(ahora=dt.datetime.fromisoformat(cuando), cot=cot, cotp=cotp)
    despues = huellas()
    cambios = sorted(p for p in set(antes) | set(despues) if antes.get(p) != despues.get(p))
    print(f"\n[{cuando}] {nota}\n  {r['titulo']} · {r['texto']}\n  archivos cambiados: {len(cambios)}")
    return cambios


def cot(b, e):
    return {"BTC": (b - 0.01, b), "ETH": (e - 0.01, e)}


# Día 16: revisión a las 00:12 UTC del 17
agregar("2026-11-16")
ch = revisar("2026-11-17T00:12:00+00:00", cot(64120, 1801), cot(64100, 1786), "cierre del 16")
assert ch, "la primera revisión del 16 debía cambiar archivos"
# La misma revisión otra vez (como las revisiones de seguridad de la misma noche): no debe cambiar nada
ch = revisar("2026-11-17T01:07:00+00:00", cot(64300, 1805), cot(64280, 1790), "otra vez el cierre del 16 (seguridad)")
assert ch == [], ch
ch = revisar("2026-11-17T02:17:00+00:00", None, None, "tercera vez, sin cotización inyectada (no debe pedirla)")
assert ch == [], ch
agregar("2026-11-17")
# Día 17: BTC rompe el máximo de 10 cierres → la regla cierra el corto de BTC
ch = revisar("2026-11-18T00:31:00+00:00", cot(72510, 1791), cot(72490, 1776), "cierre del 17 (BTC sube fuerte)")
sa = AD.cargar_estado()
assert "BTC" not in sa["libro"]["cortos"] and "ETH" in sa["libro"]["cortos"], sa["libro"]["cortos"]
agregar("2026-11-18")
agregar("2026-11-19")
# Se salta el 18 (no corrió) y revisa el 19 a las 03:40 UTC (tarde: más de 3 h)
ch = revisar("2026-11-20T03:40:00+00:00", cot(74010, 1701), cot(73990, 1686), "cierre del 19 (faltó el 18, tarde)")
# 20 nov 00:05 UTC del 21: Binance aún no entrega el cierre del 20
ch = revisar("2026-11-21T00:05:00+00:00", cot(74000, 1700), cot(73980, 1685), "cierre del 20 sin datos")
ch2 = revisar("2026-11-21T00:40:00+00:00", cot(74000, 1700), cot(73980, 1685), "otra vez sin datos")
assert ch2 == [], ch2

st = P.cargar_estado()
filas = P.leer(P.DIARIO)
print("\nDiario (fecha_cierre, hora, atraso, días sin revisión):",
      [(r["fecha_cierre"], r["hora"], r["atraso_h"], r["dias_sin_revision"]) for r in filas])
ideal = P.leer(P.IDEAL)
print("Ideal (cierres):", [r["fecha"] for r in ideal])
assert [r["fecha"] for r in ideal] == ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]
assert [r["fecha_cierre"] for r in filas] == ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-19"]
assert filas[-1]["dias_sin_revision"] == "1"
ad_ideal = [r["fecha"] for r in P.leer(AD.IDEAL)]
assert ad_ideal == ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"], ad_ideal
# Financiación horaria del corto de ETH en la práctica: cada cobro desde que se abrió hasta el último guardado
k = sa = AD.cargar_estado()["libro"]["cortos"]["ETH"]
eventos = [(int(r[0]), float(r[1]), float(r[2]) if r[2] else None) for r in list(csv.reader(open(F.ruta_financiacion("ETH"))))[1:]]
validos = [(m, t, p) for m, t, p in eventos if 1794814038702 < m <= k["fin_ms"]]
esperado = sum(k["cant"] * p * t for m, t, p in validos)
print(f"Financiación ETH: {k['n_fin']} cobros horarios, {k['fin']:.6f} USD (esperado {len(validos)} cobros, "
      f"{esperado:.6f}); último cobro {dt.datetime.fromtimestamp(k['fin_ms'] / 1000, dt.UTC)}")
assert k["n_fin"] == len(validos) == 17 + 3 * 24 and abs(k["fin"] - esperado) < 1e-12
V = P.velas()
R = reporte.calcular(st, V, P.senales(V))
print("Compuerta B:")
for ok, t in R["compuerta"]:
    print("  ", "✓" if ok else "✗", t)
print("Cuenta:", R["cuenta"], "· a tiempo", R["salud"]["a_tiempo"], "de", R["salud"]["contables"])
assert R["salud"]["contables"] == 3 and R["salud"]["a_tiempo"] == 2
assert R["cuenta"]["minima"] == "2026-12-14" and R["cuenta"]["tope"] == "2027-01-11"
h = open("informe.html", encoding="utf-8").read()
datos = json.loads(h[h.index("const DATOS = ") + 14:h.index("; const DATOS_E1")])
print("Gráfica etapa 2:", datos)
assert datos[0] == {"f": "2026-11-15", "t": 100.0, "m": 100.0, "a": 100.0}
assert [d["f"] for d in datos] == ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-19"]
assert "Binance aún no entrega el cierre del 2026-11-20" in h
print("\nTODO BIEN")

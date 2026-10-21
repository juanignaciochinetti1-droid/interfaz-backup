"""Chequeos de los servidores de copias: conexión, almacenamiento y última copia."""

import heapq
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime

import avisos

try:
    import paramiko  # solo necesario para servidores en modo "ssh"
except ImportError:
    paramiko = None


class SinAcceso(Exception):
    """El servidor responde pero rechaza usuario/contraseña (o faltan configurarlos)."""


def hacer_ping(host, timeout_s=2):
    flag = "-n" if platform.system() == "Windows" else "-c"
    tflag = ["-w", str(timeout_s * 1000)] if platform.system() == "Windows" else ["-W", str(timeout_s)]
    try:
        r = subprocess.run(["ping", flag, "1", *tflag, host],
                           capture_output=True, timeout=timeout_s + 3)
        return r.returncode == 0
    except Exception:
        return False


def probar_puerto(host, puerto, timeout_s=3):
    try:
        with socket.create_connection((host, puerto), timeout=timeout_s):
            return True
    except OSError:
        return False


def fecha(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")


def faltan_credenciales(srv):
    return "CAMBIAR" in str(srv.get("usuario", "")) or "CAMBIAR" in str(srv.get("password", ""))


# ---------- Modo "ruta": carpeta local, unidad de red o ruta UNC (\\servidor\backups) ----------

def conectar_recurso_red(ruta, usuario, password):
    """Si la ruta es de red (\\\\servidor\\recurso\\...) la conecta con usuario/contraseña (Windows)."""
    partes = [p for p in ruta.replace("/", "\\").split("\\") if p]
    if not ruta.startswith("\\\\") or len(partes) < 2:
        return
    recurso = f"\\\\{partes[0]}\\{partes[1]}"
    r = subprocess.run(["net", "use", recurso, password, f"/user:{usuario}", "/persistent:no"],
                       capture_output=True, timeout=30)
    if r.returncode != 0:
        salida = (r.stderr or r.stdout).decode("cp850", errors="replace")
        m = re.search(r"(\d+)\.", salida)
        codigo = m.group(1) if m else ""
        if codigo == "1219":  # ya hay una conexión abierta a ese servidor; se puede seguir
            return
        if codigo in ("5", "86", "1326"):
            raise SinAcceso("rechaza el usuario o la contraseña")
        if codigo in ("53", "67"):
            raise RuntimeError("no existe la carpeta compartida")
        raise RuntimeError("no se pudo conectar a la carpeta compartida")


def info_ruta(srv, limite):
    ruta = srv["ruta_backups"]
    if srv.get("usuario") and not os.path.isdir(ruta):
        if faltan_credenciales(srv):
            raise SinAcceso("faltan configurar usuario y contraseña")
        conectar_recurso_red(ruta, srv["usuario"], srv.get("password", ""))
    if not os.path.isdir(ruta):
        raise RuntimeError("no se puede abrir la carpeta")
    uso = shutil.disk_usage(ruta)

    archivos = []  # (mtime, tamaño, ruta relativa) — se guardan solo los más nuevos
    base = ruta.rstrip("\\/")
    for raiz, dirs, nombres in os.walk(base):
        if raiz[len(base):].count(os.sep) >= 2:
            dirs[:] = []
        for a in nombres:
            p = os.path.join(raiz, a)
            try:
                st = os.stat(p)
            except OSError:
                continue
            item = (st.st_mtime, st.st_size, os.path.relpath(p, base))
            if len(archivos) < limite:
                heapq.heappush(archivos, item)
            else:
                heapq.heappushpop(archivos, item)
    archivos.sort(reverse=True)
    return uso.total, uso.used, uso.free, archivos


# ---------- Modo "ssh": servidor Linux ----------

def info_ssh(srv, limite):
    if paramiko is None:
        raise RuntimeError("falta instalar paramiko (pip install paramiko)")
    if faltan_credenciales(srv):
        raise SinAcceso("faltan configurar usuario y contraseña")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(srv["host"], port=srv.get("puerto", 22), username=srv.get("usuario"),
                    password=srv.get("password") or None,
                    key_filename=srv.get("clave_privada") or None, timeout=8,
                    allow_agent=False, look_for_keys=False)
    except paramiko.AuthenticationException:
        raise SinAcceso("rechaza el usuario o la contraseña")
    try:
        ruta = srv["ruta_backups"].replace("'", "")

        def run(cmd):
            _, out, err = cli.exec_command(cmd, timeout=60)
            return out.read().decode(errors="replace").strip(), err.read().decode(errors="replace").strip()

        out, _ = run(f"df -P -B1 '{ruta}' | tail -1")
        if not out:
            raise RuntimeError("no se encuentra la carpeta")
        partes = out.split()
        total, usado, libre = int(partes[1]), int(partes[2]), int(partes[3])

        out, _ = run(f"find '{ruta}' -maxdepth 3 -type f -printf '%T@\\t%s\\t%P\\n' 2>/dev/null "
                     f"| sort -nr | head -{int(limite)}")
        archivos = []
        for linea in out.splitlines():
            t, s, p = linea.split("\t", 2)
            archivos.append((float(t), int(s), p))
        return total, usado, libre, archivos
    finally:
        cli.close()


# ---------- Monitor ----------

TEXTO_ESTADO = {"ok": "OK", "alerta": "ALERTA", "sin_acceso": "SIN ACCESO", "error": "SIN CONEXIÓN"}


class Monitor:
    def __init__(self, config, carpeta_datos):
        self.config = config
        self.estado = {}      # nombre -> último resultado
        self.lock = threading.Lock()
        os.makedirs(carpeta_datos, exist_ok=True)
        self.archivo_datos = os.path.join(carpeta_datos, "monitor.json")
        datos = self._leer_datos()
        self.alertas = datos.get("alertas", [])            # historial de eventos
        self.silencios = datos.get("silencios", {})        # nombre -> timestamp hasta cuándo
        self.limite_archivos = int(config.get("archivos_por_carpeta", 100))

    # ----- persistencia (historial y silencios sobreviven a reinicios) -----

    def _leer_datos(self):
        try:
            with open(self.archivo_datos, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _guardar_datos(self):
        tmp = self.archivo_datos + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"alertas": self.alertas, "silencios": self.silencios}, f, ensure_ascii=False)
        os.replace(tmp, self.archivo_datos)

    # ----- silencios -----

    def silenciado_hasta(self, nombre):
        hasta = self.silencios.get(nombre)
        if hasta and hasta > time.time():
            return hasta
        return None

    def silenciar(self, nombre, minutos):
        with self.lock:
            if minutos and minutos > 0:
                self.silencios[nombre] = time.time() + minutos * 60
                texto = f"Alertas silenciadas por {minutos // 60} h" if minutos >= 60 else f"Alertas silenciadas por {minutos} min"
            else:
                self.silencios.pop(nombre, None)
                texto = "Se reactivaron las alertas"
            self._agregar_evento(nombre, texto, "info")
            if nombre in self.estado:
                self._marcar_silencio(self.estado[nombre])
            self._guardar_datos()

    def _marcar_silencio(self, r):
        hasta = self.silenciado_hasta(r["nombre"])
        r["silenciado"] = bool(hasta)
        r["silenciado_hasta"] = fecha(hasta) if hasta else None

    # ----- historial -----

    def _agregar_evento(self, servidor, mensaje, nivel):
        self.alertas.insert(0, {
            "fecha": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "servidor": servidor, "mensaje": mensaje, "nivel": nivel,
        })
        del self.alertas[int(self.config.get("eventos_a_guardar", 500)):]

    def limpiar_historial(self):
        with self.lock:
            self.alertas = []
            self._guardar_datos()

    # ----- chequeos -----

    def _buscar(self, nombre):
        return next((s for s in self.config["servidores"] if s["nombre"] == nombre), None)

    def chequear(self, srv):
        nombre = srv["nombre"]
        intervalo = srv.get("intervalo_minutos", 30)
        tolerancia = srv.get("tolerancia_minutos", 5)
        r = {
            "nombre": nombre, "intervalo": intervalo,
            "ping": None, "puerto_ok": None, "conectado": False,
            "total": None, "usado": None, "libre": None, "porcentaje": None,
            "ultima_copia": None, "minutos_desde_copia": None, "archivos": [],
            "estado": "error", "mensaje": "", "chequeado": datetime.now().strftime("%H:%M:%S"),
        }

        # 1) Conectividad
        if srv.get("host"):
            r["ping"] = hacer_ping(srv["host"])
            if srv.get("puerto"):
                r["puerto_ok"] = probar_puerto(srv["host"], srv["puerto"])

        if r["ping"] is False and r["puerto_ok"] is not True:
            r["mensaje"] = "El servidor no responde (apagado o sin red)"
            return self._registrar(nombre, r)

        # 2) Almacenamiento y archivos
        try:
            if srv.get("modo") == "ssh":
                total, usado, libre, archivos = info_ssh(srv, self.limite_archivos)
            else:
                total, usado, libre, archivos = info_ruta(srv, self.limite_archivos)
        except SinAcceso as e:
            r["estado"] = "sin_acceso"
            r["mensaje"] = f"El servidor responde, pero {e}"
            return self._registrar(nombre, r)
        except Exception as e:
            r["mensaje"] = f"El servidor responde, pero {e}" if r["ping"] or r["puerto_ok"] else f"Sin conexión: {e}"
            return self._registrar(nombre, r)

        r["conectado"] = True
        r.update(total=total, usado=usado, libre=libre,
                 porcentaje=round(usado * 100 / total, 1) if total else 0)
        ahora = time.time()
        r["archivos"] = [{"nombre": p, "fecha": fecha(t), "ts": t, "tamano": s,
                          "minutos": round((ahora - t) / 60)} for t, s, p in archivos]

        # 3) ¿Se hizo la copia a tiempo?
        alerta_disco = srv.get("alerta_disco_porcentaje", 90)
        if not archivos:
            r["estado"], r["mensaje"] = "alerta", "No se encontró ninguna copia en la carpeta"
        else:
            ultima = archivos[0][0]
            mins = (ahora - ultima) / 60
            r["ultima_copia"] = fecha(ultima)
            r["minutos_desde_copia"] = round(mins)
            if mins > intervalo + tolerancia:
                r["estado"] = "alerta"
                r["mensaje"] = f"No se hizo la copia: la última fue hace {round(mins)} min (se espera cada {intervalo} min)"
            elif r["porcentaje"] >= alerta_disco:
                r["estado"] = "alerta"
                r["mensaje"] = f"Disco casi lleno ({r['porcentaje']}%)"
            else:
                r["estado"], r["mensaje"] = "ok", "Copias al día"

        return self._registrar(nombre, r)

    def _registrar(self, nombre, r):
        aviso = None
        with self.lock:
            self._marcar_silencio(r)
            anterior = self.estado.get(nombre)
            cambio = anterior is None or anterior["estado"] != r["estado"]
            if cambio and (anterior is not None or r["estado"] != "ok"):
                self._agregar_evento(nombre, r["mensaje"], r["estado"])
                self._guardar_datos()
                # Avisar por mail/Telegram (no al arrancar ni si está silenciada)
                if anterior is not None and not r["silenciado"]:
                    aviso = (f"[Copias] {nombre}: {TEXTO_ESTADO[r['estado']]}",
                             f"Carpeta: {nombre}\nEstado: {TEXTO_ESTADO[r['estado']]}\n"
                             f"Antes: {TEXTO_ESTADO[anterior['estado']]}\nDetalle: {r['mensaje']}\n"
                             f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            self.estado[nombre] = r
        if aviso:
            avisos.enviar(self.config.get("avisos"), *aviso)
        return r

    def chequear_uno(self, nombre):
        srv = self._buscar(nombre)
        if srv is None:
            return None
        return self.chequear(srv)

    def chequear_todos(self):
        hilos = [threading.Thread(target=self.chequear, args=(s,)) for s in self.config["servidores"]]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

    def iniciar(self):
        def bucle():
            while True:
                self.chequear_todos()
                time.sleep(self.config.get("chequeo_cada_segundos", 60))
        threading.Thread(target=bucle, daemon=True).start()

    def resumen(self):
        with self.lock:
            orden = [s["nombre"] for s in self.config["servidores"]]
            servidores = []
            for n in orden:
                if n in self.estado:
                    self._marcar_silencio(self.estado[n])  # por si venció el silencio
                    servidores.append(self.estado[n])
            return {
                "servidores": servidores,
                "alertas": list(self.alertas),
                "avisos": avisos.activos(self.config.get("avisos")),
                "ahora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            }

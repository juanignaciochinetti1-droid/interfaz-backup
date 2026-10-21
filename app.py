"""Interfaz web de monitoreo de servidores de copias.

Uso:  python app.py   ->  abrir http://localhost:5050
"""

import json
import os

from flask import Flask, jsonify, render_template, request

import avisos
from monitor import Monitor

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get("BACKUP_CONFIG", os.path.join(BASE, "config.json"))
DATOS = os.environ.get("BACKUP_DATOS", os.path.join(BASE, "data"))

with open(CONFIG, encoding="utf-8") as f:
    config = json.load(f)

app = Flask(__name__)
monitor = Monitor(config, DATOS)


def nombre_pedido():
    return (request.get_json(silent=True) or {}).get("nombre")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/archivos")
def archivos():
    return render_template("archivos.html")


@app.route("/api/estado")
def api_estado():
    return jsonify(monitor.resumen())


@app.route("/api/chequear", methods=["POST"])
def api_chequear():
    nombre = nombre_pedido()
    if nombre:
        if monitor.chequear_uno(nombre) is None:
            return jsonify(error="No existe esa carpeta"), 404
    else:
        monitor.chequear_todos()
    return jsonify(monitor.resumen())


@app.route("/api/silenciar", methods=["POST"])
def api_silenciar():
    datos = request.get_json(silent=True) or {}
    nombre = datos.get("nombre")
    if not monitor._buscar(nombre):
        return jsonify(error="No existe esa carpeta"), 404
    monitor.silenciar(nombre, int(datos.get("minutos", 0)))
    return jsonify(monitor.resumen())


@app.route("/api/historial/limpiar", methods=["POST"])
def api_limpiar_historial():
    monitor.limpiar_historial()
    return jsonify(monitor.resumen())


@app.route("/api/avisos/probar", methods=["POST"])
def api_probar_avisos():
    if not avisos.activos(config.get("avisos")):
        return jsonify(error="No hay avisos por mail ni Telegram activados en la configuración"), 400
    res = avisos.enviar(config.get("avisos"), "[Copias] Prueba de aviso",
                        "Si ves este mensaje, los avisos del monitor de copias funcionan.", esperar=True)
    return jsonify(resultados=res)


if __name__ == "__main__":
    monitor.iniciar()
    host, puerto = config.get("host_web", "0.0.0.0"), config.get("puerto_web", 5050)
    try:
        from waitress import serve  # servidor web estable para dejarlo corriendo
        print(f"Monitor de copias en http://{host}:{puerto}")
        serve(app, host=host, port=puerto, threads=8)
    except ImportError:
        app.run(host=host, port=puerto)

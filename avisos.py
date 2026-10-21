"""Envío de avisos por mail y Telegram cuando una carpeta cambia de estado."""

import json
import smtplib
import threading
import urllib.parse
import urllib.request
from email.mime.text import MIMEText


def _email(cfg, asunto, texto):
    msg = MIMEText(texto, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = cfg.get("remitente") or cfg["usuario"]
    msg["To"] = ", ".join(cfg["destinatarios"])
    puerto = int(cfg.get("puerto", 587))
    if puerto == 465:
        smtp = smtplib.SMTP_SSL(cfg["servidor"], puerto, timeout=20)
    else:
        smtp = smtplib.SMTP(cfg["servidor"], puerto, timeout=20)
        smtp.starttls()
    with smtp:
        if cfg.get("usuario"):
            smtp.login(cfg["usuario"], cfg.get("password", ""))
        smtp.send_message(msg)


def _telegram(cfg, asunto, texto):
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    datos = urllib.parse.urlencode({"chat_id": cfg["chat_id"], "text": f"{asunto}\n\n{texto}"}).encode()
    with urllib.request.urlopen(url, data=datos, timeout=20) as r:
        if not json.loads(r.read()).get("ok"):
            raise RuntimeError("Telegram rechazó el mensaje")


CANALES = {"email": _email, "telegram": _telegram}


def activos(config_avisos):
    return [n for n in CANALES if (config_avisos or {}).get(n, {}).get("activo")]


def enviar(config_avisos, asunto, texto, esperar=False):
    """Envía por todos los canales activos. Devuelve {canal: 'ok' | error} si esperar=True."""
    resultados = {}

    def trabajo():
        for nombre in activos(config_avisos):
            try:
                CANALES[nombre](config_avisos[nombre], asunto, texto)
                resultados[nombre] = "ok"
            except Exception as e:
                resultados[nombre] = str(e)
                print(f"[avisos] Error enviando por {nombre}: {e}")

    if esperar:
        trabajo()
        return resultados
    threading.Thread(target=trabajo, daemon=True).start()
    return None

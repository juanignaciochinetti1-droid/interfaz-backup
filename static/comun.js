// Funciones compartidas por las dos vistas
const ETIQUETA = { ok: "OK", alerta: "ALERTA", sin_acceso: "SIN ACCESO", error: "SIN CONEXIÓN", info: "INFO" };
const COLOR = { ok: "var(--ok)", alerta: "var(--warn)", sin_acceso: "var(--acc)", error: "var(--err)", info: "var(--muted)" };
const PRIORIDAD = { error: 0, sin_acceso: 1, alerta: 2, ok: 3 };

function gb(b) { return b == null ? "—" : (b / 1024 ** 3).toFixed(1) + " GB"; }

function tamano(b) {
  if (b == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return (i ? b.toFixed(1) : b) + " " + u[i];
}

function hace(min) {
  if (min == null) return "—";
  if (min < 60) return `hace ${min} min`;
  if (min < 60 * 24) return `hace ${Math.floor(min / 60)} h ${min % 60} min`;
  return `hace ${Math.floor(min / 1440)} días`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Preferencias del usuario en el navegador (filtros, vista, etc.)
function pref(clave, defecto) {
  try { const v = localStorage.getItem("mc." + clave); return v == null ? defecto : JSON.parse(v); }
  catch { return defecto; }
}
function guardarPref(clave, valor) {
  try { localStorage.setItem("mc." + clave, JSON.stringify(valor)); } catch { }
}

async function api(ruta, datos) {
  const r = await fetch(ruta, datos === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "Error del servidor");
  return j;
}

// ---------- Avisos en pantalla: notificación del navegador + sonido ----------

let avisosPantalla = pref("avisosPantalla", false);
let estadosPrevios = null;

function sonar() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.25].forEach(t => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = 880;
      g.gain.setValueAtTime(0.25, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.2);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
    });
  } catch { }
}

function notificar(titulo, texto) {
  sonar();
  if ("Notification" in window && Notification.permission === "granted") {
    try { new Notification(titulo, { body: texto }); } catch { }
  }
}

function revisarCambios(d) {
  const actuales = Object.fromEntries(d.servidores.map(s => [s.nombre, s]));
  if (estadosPrevios && avisosPantalla) {
    for (const s of d.servidores) {
      const antes = estadosPrevios[s.nombre];
      if (antes && antes !== s.estado && s.estado !== "ok" && !s.silenciado) {
        notificar(`${s.nombre}: ${ETIQUETA[s.estado]}`, s.mensaje);
      }
    }
  }
  estadosPrevios = Object.fromEntries(Object.entries(actuales).map(([n, s]) => [n, s.estado]));
}

function pintarBotonAvisos() {
  const b = document.getElementById("btnAvisos");
  if (!b) return;
  b.textContent = avisosPantalla ? "🔔 Avisos activados" : "🔕 Avisos desactivados";
  b.classList.toggle("on", avisosPantalla);
  b.title = "Sonido y notificación en esta PC cuando una carpeta pasa a alerta";
}

async function alternarAvisos() {
  avisosPantalla = !avisosPantalla;
  if (avisosPantalla) {
    if ("Notification" in window && Notification.permission === "default") {
      try { await Notification.requestPermission(); } catch { }
    }
    sonar(); // confirma que el sonido funciona
  }
  guardarPref("avisosPantalla", avisosPantalla);
  pintarBotonAvisos();
}

// ---------- Arranque común ----------

function iniciar(pintar) {
  let ultimo = null;
  const pintarTodo = d => { ultimo = d; revisarCambios(d); pintar(d); };

  const cargar = async () => {
    try { pintarTodo(await api("/api/estado")); }
    catch { document.getElementById("actualizado").textContent = "No se pudo contactar al monitor"; }
  };

  const b = document.getElementById("btn");
  b.onclick = async () => {
    b.disabled = true; b.textContent = "Chequeando…";
    try { pintarTodo(await api("/api/chequear", {})); }
    finally { b.disabled = false; b.textContent = "Chequear todo"; }
  };

  const ba = document.getElementById("btnAvisos");
  if (ba) { ba.onclick = alternarAvisos; pintarBotonAvisos(); }

  cargar();
  setInterval(cargar, 15000);
  return { repintar: () => ultimo && pintar(ultimo), aplicar: pintarTodo };
}

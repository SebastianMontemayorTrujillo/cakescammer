"use strict";

const $ = (id) => document.getElementById(id);
const numero = (v, decimales = 1) => Number(v).toLocaleString("es-MX", {maximumFractionDigits: decimales});
const fraccion = (m) => m ? `${m.numerador}/${m.denominador}` : "Sin medición";
const porcentaje = (m) => m?.denominador ? `${numero(100 * m.proporcion)}%` : "N/A";
const corto = (id) => id ? id.slice(0, 12) : "Sin identificador";
const dinero = (v, decimales = 4) => v == null ? "No medido" : `$${numero(v, decimales)}`;
const fecha = (v) => new Date(v).toLocaleString("es-MX", {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "America/Monterrey"});
const estados = {INTERRUMPIDO: "Interrumpida", DETENIDO_SIN_MEJORA: "Detenida sin mejora", LIMITE_DE_GENERACIONES: "Límite de generaciones", EN_CURSO: "En curso", EVALUADA: "Evaluada", INCOMPLETA: "Incompleta"};
let datos = null;
let modo = "real";
let seleccion = {real: null, simulacion: null};
let cargando = false;

function elemento(tag, texto, clase) {
  const nodo = document.createElement(tag);
  if (texto != null) nodo.textContent = texto;
  if (clase) nodo.className = clase;
  return nodo;
}

function poner(id, texto) { $(id).textContent = texto; }
function etiqueta(nodo, texto, color = "neutra") { nodo.textContent = texto; nodo.className = `etiqueta ${color}`; }
function filas(id, pares) {
  $(id).replaceChildren(...pares.map(([nombre, valor]) => {
    const fila = elemento("div");
    fila.append(elemento("dt", nombre), elemento("dd", valor));
    return fila;
  }));
}

function ultimaPublicada(corrida) {
  return corrida?.generaciones.filter(g => g.publicada === true).at(-1) || corrida?.baseline;
}

function dibujar(corrida) {
  const contenedor = $("grafico");
  contenedor.replaceChildren();
  if (!corrida) {
    contenedor.append(elemento("p", "No hay una corrida disponible para comparar.", "texto-secundario"));
    contenedor.setAttribute("aria-label", "Sin mediciones");
    return;
  }
  const puntos = [{nombre: "Base", ...corrida.baseline}, ...corrida.generaciones.map(g => ({nombre: `Gen. ${g.numero}`, ...g}))];
  const ancho = Math.max(480, contenedor.clientWidth - 48);
  const alto = 245, izquierda = 45, derecha = ancho - 48, arriba = 38, abajo = 197;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${ancho} ${alto}`);
  const crear = (tag, atributos, texto) => {
    const n = document.createElementNS(svg.namespaceURI, tag);
    Object.entries(atributos).forEach(([k, v]) => n.setAttribute(k, v));
    if (texto != null) n.textContent = texto;
    svg.append(n); return n;
  };
  [0, 25, 50, 75, 100].forEach(p => {
    const y = abajo - (p / 100) * (abajo - arriba);
    crear("line", {x1: izquierda, x2: derecha, y1: y, y2: y, class: "rejilla"});
    crear("text", {x: izquierda - 12, y: y + 4, "text-anchor": "end"}, `${p}%`);
  });
  let padre = null;
  const descripcion = [];
  puntos.forEach((p, i) => {
    const x = puntos.length === 1 ? (izquierda + derecha) / 2 : izquierda + i * (derecha - izquierda) / (puntos.length - 1);
    const m = p.metricas?.funcional;
    const valida = m?.denominador > 0;
    const y = valida ? abajo - m.proporcion * (abajo - arriba) : abajo;
    if (i && padre && valida && p.comparacion?.funcional?.comparable) {
      crear("path", {d: `M ${padre.x} ${padre.y} L ${x} ${y}`, class: p.publicada ? "trayecto" : "trayecto-rechazo"});
    }
    if (valida) {
      crear("circle", {cx: x, cy: y, r: 6, class: i === 0 ? "punto-base" : p.publicada ? "punto-aceptado" : "punto-rechazado"});
      crear("text", {x: i === 0 ? x + 10 : x, y: y - 16, "text-anchor": i === 0 ? "start" : "middle", class: "numero"}, fraccion(m));
    }
    crear("text", {x, y: 223, "text-anchor": "middle"}, p.nombre);
    if (!valida) crear("text", {x, y: abajo - 10, "text-anchor": "middle"}, "N/A");
    descripcion.push(`${p.nombre}: ${fraccion(m)}${i ? p.publicada ? ", publicada" : ", no publicada" : ""}`);
    if (valida && (i === 0 || p.publicada)) padre = {x, y};
  });
  contenedor.setAttribute("aria-label", descripcion.join(". "));
  contenedor.append(svg);
}

function mostrarReserva(linea) {
  const reserva = linea.evaluaciones.filter(e => e.particion === "reservada").at(-1);
  const vigente = linea.evaluaciones.find(e => e.id === linea.reserva_actual_id);
  poner("kpi-reserva", vigente ? fraccion(vigente.metricas.funcional) : "—");
  poner("kpi-reserva-nota", vigente ? `${porcentaje(vigente.metricas.funcional)} · misma revisión del código` : "Sin reserva de la revisión actual");
  if (!reserva) {
    etiqueta($("reserva-etiqueta"), "No evaluada");
    filas("reserva-datos", [["Evidencia", "No hay reporte reservado"]]);
    poner("reserva-nota", "La ausencia de una medición no equivale a una aprobación.");
    return;
  }
  const coincide = reserva.coincide_runtime_activo === true;
  const completa = reserva.estado === "EVALUADA" && reserva.integridad === true && reserva.completitud?.proporcion === 1;
  etiqueta($("reserva-etiqueta"), !coincide ? "Histórica · otra revisión" : completa ? "Evaluación completa" : "Incompleta o sin validar", coincide && completa ? "verde" : "ambar");
  filas("reserva-datos", [
    ["Tipo de evidencia", modo === "real" ? "Modelo real" : "Determinista"],
    ["Estado / integridad", `${estados[reserva.estado] || "Desconocido"} / ${reserva.integridad === true ? "verificada" : reserva.integridad === false ? "fallida" : "sin verificar"}`],
    ["Conversaciones completas", fraccion(reserva.completitud)],
    ["Objetivos cumplidos", fraccion(reserva.metricas.funcional)],
    ["Controles de seguridad", fraccion(reserva.metricas.seguridad)],
    ["Latencia p95 por conversación", reserva.operacion.latencia_p95_segundos == null ? "No medida" : `${numero(reserva.operacion.latencia_p95_segundos, 2)} s`],
    ["Costo de esta evaluación · USD", dinero(reserva.operacion.costo_total_usd, 7)],
    ["Contenido evaluado", `${corto(reserva.version_id)}${coincide ? " · activa" : " · otra versión o sin verificar"}`],
    ["Código del harness evaluado", corto(reserva.configuracion?.arnes_sha256)],
  ]);
  const m = reserva.metricas.funcional;
  poner("reserva-nota", `${!coincide ? "Este resultado no valida el código actual. " : ""}${m ? `${m.denominador - m.numerador} objetivos incumplidos. ` : ""}Sin comparación con una base reservada. Fuente: ${reserva.fuente}`);
}

function mostrarComercial(corrida) {
  const base = corrida?.baseline.comercial, final = ultimaPublicada(corrida)?.comercial;
  if (!base || !final) { filas("comercial-datos", [["Medición", "Sin evidencia comercial"]]); return; }
  const publicadas = corrida.generaciones.filter(g => g.publicada === true);
  const comparable = (nombre) => publicadas.every(g => g.comparacion?.comercial?.[nombre]?.comparable);
  const comparar = (nombre) => comparable(nombre) ? `${fraccion(base.metricas[nombre])} → ${fraccion(final.metricas[nombre])}` : `${fraccion(final.metricas[nombre])} · sin comparación válida`;
  const ticket = (t) => t ? `${dinero(t.promedio_centavos == null ? null : t.promedio_centavos / 100, 0)} · N=${t.denominador}` : "No medido";
  filas("comercial-datos", [
    ["Oportunidades de valor", comparar("oportunidad_valor")],
    ["Cierre preparado", comparar("cierre_preparado")],
    ["Controles comerciales", comparar("seguridad")],
    ["Ticket potencial base · MXN", ticket(base.ticket_potencial)],
    ["Ticket potencial final · MXN", ticket(final.ticket_potencial)],
    ["Comparación del ticket", publicadas.every(g => g.comparacion?.ticket_potencial?.comparable) ? "Mismo instrumento y denominador" : "No comparable; solo valores observados"],
  ]);
}

function mostrarExperiencia() {
  const reportes = datos.experiencia?.[modo === "real" ? "real" : "offline"] || [];
  const actual = reportes.filter(r => r.coincide_runtime_activo).at(-1);
  etiqueta($("experiencia-etiqueta"), actual ? actual.cumple_automatico === true ? "Revisión actual · cumple" : "Revisión actual · con fallos" : "Revisión actual sin evaluar", actual?.cumple_automatico === true ? "verde" : "ambar");
  const contenedor = $("experiencia-resultados");
  contenedor.replaceChildren();
  if (!reportes.length) { contenedor.append(elemento("p", "Aún no hay mediciones de experiencia en esta línea.", "texto-secundario")); return; }
  const tabla = elemento("table"), head = elemento("thead"), titulos = elemento("tr"), body = elemento("tbody");
  ["Medición · Monterrey", "Código evaluado", "Objetivos", "Seguridad", "Conversaciones", "Estado"].forEach(t => { const th = elemento("th", t); th.scope = "col"; titulos.append(th); });
  head.append(titulos); tabla.append(head);
  reportes.forEach(r => {
    const fila = elemento("tr");
    [fecha(r.fecha), `${corto(r.arnes_sha256)} · ${r.coincide_runtime_activo ? "actual" : "anterior"}`, fraccion(r.metricas.objetivos), fraccion(r.metricas.seguridad), fraccion(r.completitud), `${estados[r.estado] || "Sin verificar"}${r.cumple_automatico === true ? " · cumple" : " · no aprobada"}`].forEach(t => fila.append(elemento("td", t)));
    body.append(fila);
  });
  tabla.append(body); contenedor.append(tabla);
  contenedor.tabIndex = 0; contenedor.setAttribute("aria-label", "Resultados por revisión del código; desplaza para ver todas las columnas");
}

function mostrarVersion(linea) {
  poner("version-id", linea.activa_id || "No hay una versión activa registrada.");
  etiqueta($("version-modo"), modo === "real" ? "Línea real" : "Simulación", modo === "real" ? "verde" : "ambar");
  const h = linea.harness_activo;
  filas("harness", h ? [
    ["Revisión del código", corto(linea.arnes_actual_sha256)],
    ["Cotización automática", h.cotizar_automaticamente ? "Activa" : "Inactiva"],
    ["Uso de preferencias compartidas", h.usar_preferencias ? "Activo" : "Inactivo"],
    ["Preguntas por turno", h.preguntas_por_turno],
    ["Estrategia comercial", h.estrategia_comercial === "valor" ? "Valor autorizado" : "Ajuste a la solicitud"],
    ["Cierre consultivo", h.cierre_consultivo ? "Activo" : "Inactivo"],
  ] : [["Configuración", "No disponible"]]);
}

function razonGeneracion(g) {
  const d = g.decision;
  if (g.publicada === true) return "Publicada";
  if (d.aceptado === true) return "Aprobada sin publicación";
  if (d.aceptado === false && d.victorias === 0 && d.derrotas === 0 && d.victorias_comerciales === 0 && d.derrotas_comerciales === 0) return "Empate · rechazada";
  return d.aceptado === false ? "Rechazada por la compuerta" : "Decisión incompleta";
}

function mostrarHistorial(linea) {
  const abiertos = new Set([...$("lista-historial").querySelectorAll("details[open]")].map(n => n.dataset.id));
  poner("cantidad-corridas", `${linea.corridas.length} corridas · ${linea.corridas.reduce((s, c) => s + c.publicadas, 0)} publicaciones`);
  const nodos = [...linea.corridas].reverse().map(c => {
    const articulo = elemento("article", null, "intento");
    const cabecera = elemento("div", null, "intento-cabecera");
    const estado = elemento("span");
    etiqueta(estado, estados[c.estado] || "Estado desconocido", c.estado === "INTERRUMPIDO" ? "ambar" : "neutra");
    const boton = elemento("button", "Ver curva ↗", "boton secundario");
    boton.type = "button";
    boton.setAttribute("aria-label", `Ver curva de la corrida ${c.id}`);
    boton.addEventListener("click", () => { seleccion[modo] = c.id; renderizar(); $("evolucion").scrollIntoView(); $("corrida").focus({preventScroll: true}); });
    cabecera.append(elemento("h3", c.id), estado, boton);
    const meta = elemento("div", `${fecha(c.fecha)} · Monterrey · ${c.publicadas} publicada${c.publicadas === 1 ? "" : "s"} · ${c.generaciones.length} candidata${c.generaciones.length === 1 ? "" : "s"} evaluada${c.generaciones.length === 1 ? "" : "s"}`, "intento-meta");
    const detalle = elemento("details"); detalle.dataset.id = c.id; detalle.open = abiertos.has(c.id);
    detalle.append(elemento("summary", "Ver decisiones y fuente de evidencia"));
    if (!c.generaciones.length) detalle.append(elemento("p", "El intento no produjo una candidata evaluada. No se atribuye ninguna mejora ni publicación."));
    else {
      const tabla = elemento("table"), head = elemento("thead"), titulos = elemento("tr");
      ["Generación", "Versión candidata", "Objetivos", "Seguridad", "Pareadas + / −", "Decisión"].forEach(t => { const th = elemento("th", t); th.scope = "col"; titulos.append(th); });
      head.append(titulos); tabla.append(head); const cuerpo = elemento("tbody");
      c.generaciones.forEach(g => {
        const fila = elemento("tr");
        [g.numero, corto(g.candidato), fraccion(g.metricas.funcional), fraccion(g.metricas.seguridad), `${g.decision.victorias ?? "?"} / ${g.decision.derrotas ?? "?"}`, razonGeneracion(g)].forEach(v => fila.append(elemento("td", v)));
        cuerpo.append(fila);
      });
      tabla.append(cuerpo); const scroll = elemento("div", null, "tabla-scroll"); scroll.tabIndex = 0; scroll.setAttribute("aria-label", "Decisiones por generación; desplaza para ver todas las columnas"); scroll.append(tabla); detalle.append(scroll);
      detalle.append(elemento("p", "Pareadas + / − cuenta mejoras y regresiones funcionales y de seguridad del arnés, no personas ni chats. Las mejoras comerciales pueden aprobar una generación con empate funcional."));
    }
    detalle.append(elemento("p", `Fuente: ${c.fuente}`));
    articulo.append(cabecera, meta, detalle); return articulo;
  });
  $("lista-historial").replaceChildren(...(nodos.length ? nodos : [elemento("p", "No hay intentos registrados en esta línea.", "intento")]));
}

function renderizar() {
  if (!datos) return;
  const linea = datos.modos[modo];
  if (!linea.corridas.some(c => c.id === seleccion[modo])) seleccion[modo] = [...linea.corridas].reverse().find(c => c.publicadas > 0)?.id || linea.corridas.at(-1)?.id;
  const corrida = linea.corridas.find(c => c.id === seleccion[modo]);
  $("modo-real").setAttribute("aria-pressed", modo === "real");
  $("modo-simulacion").setAttribute("aria-pressed", modo === "simulacion");
  etiqueta($("etiqueta-modo"), modo === "real" ? "MODELO REAL" : "SIMULACIÓN", modo === "real" ? "verde" : "ambar");
  poner("descripcion-modo", modo === "real" ? "Constructor y extracción con API. Evaluaciones sintéticas; suite comercial determinista." : "Constructor de reglas y extracciones preparadas. Demuestra el mecanismo; no la calidad del modelo.");
  poner("actualizado", `Leído ${new Date(datos.generado_en).toLocaleTimeString("es-MX")}`);
  $("sin-datos").hidden = !!corrida;
  $("corrida").replaceChildren(...linea.corridas.map(c => { const o = elemento("option", `${fecha(c.fecha)} · ${c.publicadas} publicada${c.publicadas === 1 ? "" : "s"}`); o.value = c.id; return o; }));
  $("corrida").value = seleccion[modo] || ""; $("corrida").disabled = !corrida;
  const final = ultimaPublicada(corrida);
  poner("kpi-funcional", final ? fraccion(final.metricas.funcional) : "—");
  poner("kpi-funcional-nota", final ? `${porcentaje(final.metricas.funcional)} · última publicada o base de esta corrida` : "Sin medición");
  poner("kpi-seguridad", final ? fraccion(final.metricas.seguridad) : "—");
  poner("kpi-seguridad-nota", final ? `${porcentaje(final.metricas.seguridad)} · controles previstos` : "Sin medición");
  const b = datos.presupuesto;
  poner("kpi-gasto", b ? dinero(b.gastado) : "—");
  poner("kpi-gasto-nota", b ? `de ${dinero(b.limite, 2)} · reservado ${dinero(b.reservado, 6)}${b.bloqueado ? " · BLOQUEADO" : ""}` : "Cuenta no disponible");
  const publicadas = corrida?.generaciones.filter(g => g.publicada) || [];
  const comparable = publicadas.length && publicadas.every(g => g.comparacion.funcional.comparable);
  if (comparable) {
    const delta = publicadas.reduce((s, g) => s + g.comparacion.funcional.delta_aciertos, 0);
    poner("mejora", `${delta >= 0 ? "+" : ""}${delta} objetivos`);
    poner("mejora-nota", `${fraccion(corrida.baseline.metricas.funcional)} → ${fraccion(final.metricas.funcional)} · ${publicadas.length} publicación${publicadas.length === 1 ? "" : "es"} confirmada${publicadas.length === 1 ? "" : "s"}`);
  } else {
    poner("mejora", corrida ? "Sin mejora publicada" : "Sin medición");
    poner("mejora-nota", corrida?.generaciones.length ? "Las candidatas no publicadas permanecen visibles." : "No hay una candidata evaluada para comparar.");
  }
  etiqueta($("estado-corrida"), corrida ? estados[corrida.estado] || "Estado desconocido" : "Sin datos", corrida?.estado === "INTERRUMPIDO" ? "ambar" : "neutra");
  poner("detalle-corrida", corrida ? `${corrida.coincide_arnes_actual ? "" : "Medición histórica: el código evaluado no coincide o no se pudo verificar con la revisión actual. "}${corrida.estado === "INTERRUMPIDO" ? "El ciclo se interrumpió. Las publicaciones confirmadas antes de la interrupción se conservan. " : "Los rechazos se registran y conservan la versión aceptada. "}Fuente: ${corrida.fuente}` : "El panel nunca ejecuta una evaluación para completar datos faltantes.");
  dibujar(corrida); mostrarReserva(linea); mostrarComercial(corrida); mostrarVersion(linea); mostrarHistorial(linea); mostrarExperiencia();
  $("avisos").hidden = !datos.numero_avisos;
  poner("avisos", datos.numero_avisos ? `${datos.numero_avisos} avisos de lectura. Hay evidencia incompleta, incompatible o no disponible; las métricas ausentes no se cuentan como aciertos. ${[...new Set(datos.avisos.map(a => a.codigo))].join(" · ")}` : "");
}

async function actualizar() {
  if (cargando) return;
  cargando = true; $("actualizar").disabled = true; $("actualizar").textContent = "Leyendo…";
  try {
    const respuesta = await fetch("/api/panel", {cache: "no-store", signal: AbortSignal.timeout(10000)});
    if (!respuesta.ok) throw new Error("lectura");
    const nuevo = await respuesta.json();
    if (nuevo.esquema !== 1 || !nuevo.modos?.real || !nuevo.modos?.simulacion) throw new Error("formato");
    datos = nuevo; $("error").hidden = true; renderizar();
  } catch {
    $("error").hidden = false;
    poner("error", `No se pudo actualizar la evidencia. ${datos ? "Se conserva la última lectura; los datos pueden estar desactualizados. " : ""}Comprueba que el servidor local siga abierto y pulsa Actualizar.`);
  } finally {
    cargando = false; $("actualizar").disabled = false; $("actualizar").textContent = "↻ Actualizar";
  }
}

["real", "simulacion"].forEach(m => $(`modo-${m}`).addEventListener("click", () => { modo = m; renderizar(); }));
$("corrida").addEventListener("change", e => { seleccion[modo] = e.target.value; renderizar(); });
$("actualizar").addEventListener("click", actualizar);
let redimensionar;
window.addEventListener("resize", () => { clearTimeout(redimensionar); redimensionar = setTimeout(() => { if (datos) dibujar(datos.modos[modo].corridas.find(c => c.id === seleccion[modo])); }, 150); });
setInterval(() => { if (!document.hidden) actualizar(); }, 30000);
actualizar();

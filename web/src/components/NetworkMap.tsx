import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { Customer, CustomerState, MapData, MapOlt } from "../api";
import { dbm } from "../format";

import { STATE_COLOR, STATE_LABEL } from "../mapStates";
export { STATE_COLOR, STATE_LABEL };

// Mapa base: OpenStreetMap (aberto, sem chave). No modo noturno um filtro de
// cor escurece as imagens (index.css), sem depender de outro fornecedor.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

const esc = (s: string | null | undefined) =>
  (s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function customerPopup(c: Customer): string {
  const where = [c.olt_name, c.pon && `PON ${c.pon}`, c.onu_index !== null && `ONU ${c.onu_index}`].filter(Boolean).join(" · ");
  return `
    <div class="lumio-popup">
      <p class="lumio-popup-title">${esc(c.name)}</p>
      <p class="lumio-popup-state" style="color:${STATE_COLOR[c.state]}">● ${STATE_LABEL[c.state]}${c.rx_dbm !== null && c.state !== "offline" ? ` · ${esc(dbm(c.rx_dbm))}` : ""}</p>
      <p>${esc(c.address)}${c.district ? ` · ${esc(c.district)}` : ""}</p>
      ${c.phone ? `<p>${esc(c.phone)}</p>` : ""}
      ${c.plan ? `<p>Plano ${esc(c.plan)}${c.code ? ` · ${esc(c.code)}` : ""}</p>` : ""}
      <p class="lumio-popup-muted">${esc(c.serial)}${where ? ` · ${esc(where)}` : ""}</p>
      <p class="lumio-popup-links">
        ${c.onu_id ? `<a href="/onus/${c.onu_id}" data-link>Ver ONU</a>` : ""}
        ${c.ticket_id ? `<a href="/alarms/${c.ticket_id}" data-link>Abrir chamado</a>` : ""}
      </p>
    </div>`;
}

function oltIcon(o: MapOlt): L.DivIcon {
  const bad = o.reachable === false || o.open_alarms > 0;
  return L.divIcon({
    className: "",
    iconSize: [0, 0],
    html: `<div class="lumio-olt ${bad ? "lumio-olt-bad" : ""}"><span></span><b>${esc(o.name)}</b></div>`,
  });
}

export interface FocusTarget {
  lat: number;
  lon: number;
  key: number;
}

/**
 * Mapa da rede: OLTs (quadrados) e clientes (pontos coloridos pelo estado da ONU).
 * Clientes sem serviço pulsam e ganham uma linha até a OLT. Navega pelo React
 * Router ao clicar nos links do cartão (onNavigate).
 */
export function NetworkMap({
  data,
  visible,
  focus,
  onNavigate,
  className = "h-[520px]",
  interactive = true,
  bare = false,
}: {
  data: MapData;
  visible: Set<CustomerState>;
  focus?: FocusTarget | null;
  onNavigate?: (path: string) => void;
  className?: string;
  interactive?: boolean;
  /** sem borda/canto próprios (quando já está dentro de um cartão) */
  bare?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tiles = useRef<L.TileLayer | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);
  const bounds = useRef<L.LatLngBounds | null>(null);
  const touched = useRef(false); // o usuário já mexeu no mapa: não reenquadra mais

  // cria o mapa uma vez
  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, {
      preferCanvas: true,
      zoomControl: interactive,
      attributionControl: true,
      scrollWheelZoom: interactive,
      dragging: interactive,
    }).setView([-22.2139, -49.9458], 13);
    tiles.current = L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    // links dentro dos cartões navegam sem recarregar a página
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest("a[data-link]") as HTMLAnchorElement | null;
      if (a && onNavigate) {
        e.preventDefault();
        onNavigate(a.getAttribute("href")!);
      }
    };
    el.current.addEventListener("click", onClick);
    const node = el.current;
    // o quadro muda de tamanho (layout carregando, gaveta, tela cheia): ajusta e reenquadra
    const touch = () => (touched.current = true);
    m.on("dragstart", touch);
    node.addEventListener("wheel", touch, { passive: true });
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      m.invalidateSize();
      if (bounds.current && !touched.current) m.fitBounds(bounds.current, { padding: [30, 30], maxZoom: 15 });
    });
    ro?.observe(node);
    return () => {
      ro?.disconnect();
      node.removeEventListener("wheel", touch);
      node.removeEventListener("click", onClick);
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // desenha OLTs e clientes a cada atualização dos dados
  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const olts = new Map(data.olts.map((o) => [o.id, o]));
    const shown = data.customers.filter((c) => visible.has(c.state) && c.lat !== null && c.lon !== null);

    // linhas OLT -> clientes sem serviço (mostra o caminho da fibra afetada)
    for (const c of shown) {
      const o = c.olt_id ? olts.get(c.olt_id) : undefined;
      if (c.state === "offline" && o?.lat != null && o.lon != null) {
        L.polyline([[o.lat, o.lon], [c.lat!, c.lon!]], { color: STATE_COLOR.offline, weight: 1.5, opacity: 0.45, dashArray: "4 4" }).addTo(g);
      }
    }
    // clientes: os normais por baixo, os com problema por cima
    const order: CustomerState[] = ["online", "unknown", "trend", "low", "offline"];
    for (const state of order) {
      for (const c of shown.filter((x) => x.state === state)) {
        if (state === "offline") {
          L.marker([c.lat!, c.lon!], {
            icon: L.divIcon({ className: "", iconSize: [0, 0], html: '<span class="lumio-pulse"></span>' }),
            keyboard: false,
          })
            .bindPopup(customerPopup(c))
            .addTo(g);
        } else {
          L.circleMarker([c.lat!, c.lon!], {
            radius: state === "online" ? 4.5 : 6,
            color: "#ffffff",
            weight: 1.5,
            fillColor: STATE_COLOR[state],
            fillOpacity: 0.95,
          })
            .bindPopup(customerPopup(c))
            .addTo(g);
        }
      }
    }
    for (const o of data.olts) {
      if (o.lat == null || o.lon == null) continue;
      L.marker([o.lat, o.lon], { icon: oltIcon(o), zIndexOffset: 1000 })
        .bindPopup(
          `<div class="lumio-popup"><p class="lumio-popup-title">${esc(o.name)}</p>
           <p>${o.onus_online}/${o.onus_total} ONUs online · ${o.open_alarms} ${o.open_alarms === 1 ? "alarme aberto" : "alarmes abertos"}</p>
           ${o.located ? "" : '<p class="lumio-popup-muted">posição estimada pelos clientes (informe no cadastro da OLT)</p>'}
           <p class="lumio-popup-links"><a href="/olts/${o.id}" data-link>Ver OLT</a></p></div>`,
        )
        .addTo(g);
    }
    // enquadra tudo na primeira carga
    if (!fitted.current) {
      const pts = [
        ...data.customers.filter((c) => c.lat !== null).map((c) => [c.lat!, c.lon!] as [number, number]),
        ...data.olts.filter((o) => o.lat != null).map((o) => [o.lat!, o.lon!] as [number, number]),
      ];
      if (pts.length) {
        bounds.current = L.latLngBounds(pts);
        m.fitBounds(bounds.current, { padding: [30, 30], maxZoom: 15 });
        fitted.current = true;
      }
    }
  }, [data, visible]);

  useEffect(() => {
    if (focus && map.current) map.current.flyTo([focus.lat, focus.lon], 17, { duration: 0.8 });
  }, [focus]);

  return <div ref={el} className={`z-0 w-full overflow-hidden ${bare ? "" : "rounded-xl border border-slate-200"} ${className}`} role="region" aria-label="Mapa da rede" />;
}

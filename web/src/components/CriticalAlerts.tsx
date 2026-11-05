import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { kindLabel } from "../format";
import type { AlarmKind } from "../api";
import { ALARM_EVENT, type LiveEvent } from "../live";
import { useToast } from "../toast";

const KEY = "lumio-alert-sound";

function enabled() {
  try {
    return localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

/** Dois bipes curtos, gerados na hora (sem arquivo de áudio). */
export function beep() {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    [0, 0.22].forEach((at, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = i ? 660 : 880;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + at);
      osc.stop(ctx.currentTime + at + 0.2);
    });
    setTimeout(() => ctx.close(), 800);
  } catch {
    /* navegador sem áudio: só o aviso visual */
  }
}

/**
 * Alarme crítico novo: aviso na tela sempre; com o alerta ligado (botão do sino),
 * também som e notificação do sistema, mesmo com a aba em segundo plano.
 */
export function CriticalAlerts() {
  const toast = useToast();
  const navigate = useNavigate();
  const [on, setOn] = useState(enabled);

  useEffect(() => {
    const onAlarm = (e: Event) => {
      const ev = (e as CustomEvent<LiveEvent>).detail;
      if (ev.type !== "alarm.opened" || ev.severity !== "critical") return;
      const label = kindLabel[ev.kind as AlarmKind] ?? "Alarme crítico";
      toast(`Novo alarme crítico: ${label}`, "alert");
      if (!enabled()) return;
      beep();
      if ("Notification" in window && Notification.permission === "granted" && document.visibilityState !== "visible") {
        const n = new Notification("Lumio · alarme crítico", {
          body: `${label}. Abra a central de alarmes.`,
          tag: ev.alarm_id,
          icon: "/favicon.svg",
        });
        n.onclick = () => {
          window.focus();
          navigate(`/alarms/${ev.alarm_id}`);
          n.close();
        };
      }
    };
    window.addEventListener(ALARM_EVENT, onAlarm);
    return () => window.removeEventListener(ALARM_EVENT, onAlarm);
  }, [toast, navigate]);

  async function toggle() {
    const next = !on;
    if (next && "Notification" in window && Notification.permission === "default") {
      await Notification.requestPermission().catch(() => "denied");
    }
    try {
      localStorage.setItem(KEY, next ? "on" : "off");
    } catch {
      /* navegação privada: vale só agora */
    }
    setOn(next);
    if (next) beep();
    toast(next ? "Alerta sonoro de críticos ligado" : "Alerta sonoro desligado");
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? "Desligar alerta sonoro de alarmes críticos" : "Ligar alerta sonoro de alarmes críticos"}
      title={on ? "Alerta de críticos: ligado (som + notificação)" : "Alerta de críticos: desligado"}
      className={`inline-flex size-8 items-center justify-center rounded-md hover:bg-slate-100 ${on ? "text-brand-600" : "text-slate-500"}`}
    >
      <svg
        viewBox="0 0 24 24"
        className="size-[18px]"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        {!on && <path d="m3 3 18 18" />}
      </svg>
    </button>
  );
}

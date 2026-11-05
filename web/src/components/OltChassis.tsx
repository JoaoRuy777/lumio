import { Link } from "react-router";
import type { ChassisOnu, ChassisPon } from "../api";
import { dbm } from "../format";
import { STATE_COLOR, STATE_LABEL } from "../mapStates";

const ORDER: ChassisOnu["state"][] = ["online", "trend", "low", "offline", "unknown"];

function tooltip(o: ChassisOnu, pon: string) {
  return [
    `PON ${pon} · ONU ${o.onu_index}`,
    o.customer ?? "sem cliente cadastrado",
    `${STATE_LABEL[o.state]}${o.rx_dbm !== null && o.state !== "offline" ? ` · ${dbm(o.rx_dbm)}` : ""}`,
    o.serial ?? "",
  ]
    .filter(Boolean)
    .join("\n");
}

/**
 * A OLT como um chassi: uma linha por porta PON e um quadradinho por ONU,
 * colorido pelo estado. Um rompimento de fibra aparece como a fileira inteira
 * em vermelho: dá para ver o problema de longe.
 */
export function OltChassis({ pons, oltId }: { pons: ChassisPon[]; oltId: string }) {
  const counts = Object.fromEntries(ORDER.map((s) => [s, 0])) as Record<ChassisOnu["state"], number>;
  for (const p of pons) for (const o of p.onus) counts[o.state]++;

  return (
    <div className="space-y-3 p-4">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Legenda">
        {ORDER.filter((s) => counts[s] > 0 || s === "online" || s === "offline").map((s) => (
          <li key={s} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={{ background: STATE_COLOR[s] }} aria-hidden />
            {STATE_LABEL[s]} <b className="text-slate-800 tabular-nums">{counts[s]}</b>
          </li>
        ))}
      </ul>

      <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
        {pons.map((p) => {
          const online = p.onus.filter((o) => o.state !== "offline" && o.state !== "unknown").length;
          return (
            <div
              key={p.id}
              className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md px-2.5 py-2 ${
                p.fiber_cut ? "bg-red-50 ring-1 ring-red-200" : "bg-surface ring-1 ring-slate-200"
              }`}
              aria-label={`PON ${p.name}`}
            >
              <div className="w-36 shrink-0">
                <Link to={`/onus?olt_id=${oltId}&pon_id=${p.id}`} className="font-mono text-sm font-semibold hover:underline">
                  PON {p.name}
                </Link>
                <p className="text-xs text-slate-500 tabular-nums">
                  {online}/{p.onus.length} online
                </p>
                {p.fiber_cut && <p className="text-xs font-semibold text-red-700">Rompimento de fibra</p>}
                {p.in_maintenance && <p className="text-xs font-medium text-sky-800">Em manutenção</p>}
              </div>
              {p.onus.length === 0 ? (
                <span className="text-xs text-slate-400">sem ONUs</span>
              ) : (
                <ul className="flex flex-1 flex-wrap gap-1" aria-label={`ONUs da PON ${p.name}`}>
                  {p.onus.map((o) => (
                    <li key={o.id}>
                      <Link
                        to={`/onus/${o.id}`}
                        title={tooltip(o, p.name)}
                        aria-label={`ONU ${o.onu_index}: ${STATE_LABEL[o.state]}`}
                        className="block size-4 rounded-[3px] ring-offset-1 ring-offset-surface transition-transform hover:scale-125 hover:ring-2 hover:ring-slate-400 focus-visible:ring-2 focus-visible:ring-brand-500"
                        style={{ background: STATE_COLOR[o.state] }}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

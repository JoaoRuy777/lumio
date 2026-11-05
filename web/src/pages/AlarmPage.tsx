import { useParams } from "react-router";
import type { Me } from "../api";
import { Ticket } from "../components/Ticket";

/** Página do chamado (/alarms/:id): o mesmo chamado do painel da central, em tela cheia. */
export function AlarmPage({ me }: { me: Me }) {
  const { id = "" } = useParams();
  return <Ticket key={id} id={id} me={me} />;
}

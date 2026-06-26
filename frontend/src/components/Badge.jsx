export default function Badge({ status, kind }) {
  if (kind) return <span className="badge kind">{kind === "reuse" ? "REUSE" : "TTS"}</span>;
  return <span className={"badge " + (status || "")}>{status}</span>;
}

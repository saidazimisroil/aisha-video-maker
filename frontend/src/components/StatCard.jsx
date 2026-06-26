export default function StatCard({ value, label, tone }) {
  return (
    <div className="stat">
      <div className={"val" + (tone ? " " + tone : "")}>{value}</div>
      <div className="lbl">{label}</div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { getAccount } from "../api/endpoints.js";
import { fmtMoney } from "../lib/format.js";

// Studio API-account balance, shown in the sidebar. Reuses the existing /api/account probe
// (app/aisha.py:get_balance). When the probe can't find a balance the card hides itself, so the
// sidebar layout is unaffected — same gate Overview uses (account?.available).
export default function BalanceCard() {
  const [account, setAccount] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getAccount()
      .then((a) => !cancelled && setAccount(a))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!account?.available || account.balance == null) return null;

  const currency = account.raw?.currency || "SO'M";

  return (
    <div className="balance-card">
      <div className="bc-label">
        <span className="bc-dot" /> SIZNING BALANSINGIZ
      </div>
      <div className="bc-amount">
        {fmtMoney(account.balance)} <span className="bc-cur">{currency}</span>
      </div>
      <div className="bc-bar">
        <span className="bc-bar-fill" />
      </div>
    </div>
  );
}

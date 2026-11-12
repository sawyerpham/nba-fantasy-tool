import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/** The kinds of push, in the order shown: settings key, label, when it goes out. */
const KINDS = [
  ["lock", "Lock calls", "30 min before the tip that closes a lock window"],
  ["swap", "Keep / swap calls", "5 min before a later bench player's tip"],
  ["out", "Player ruled OUT", "a starter ruled out before his tip, and any player on your roster newly listed Out"],
  ["dtd", "Player GTD / DTD", "a questionable starter 30 min before his tip, and any player newly listed GTD / DTD"],
  ["cleared", "Player cleared to play", "a GTD / DTD / Out player whose tag is gone (or Probable)"],
  ["moves", "Lineup moves", "the swaps to make in Sleeper, 30 min before the tip they must beat"],
];

/** Load /notify: the Telegram link and the Notifications settings; `null` while loading, `{ error }` when the API fails. */
export function useNotify() {
  const [st, setSt] = useState(null);
  useEffect(() => { api.get("/notify").then(setSt).catch((e) => setSt({ configured: false, error: e.message })); }, []);
  return [st, setSt];
}

/** "Linked to <chat> · chat <id> · Open the chat", or that Telegram isn't set up. `st` is /notify's result. */
export function TelegramLink({ st }) {
  if (!st) return <span className="muted">Checking Telegram…</span>;
  if (!st.configured) return <span data-testid="telegram-off">Telegram alerts are <strong>not set up</strong></span>;
  const who = st.chat?.name || st.chat?.username;
  return (
    <span data-testid="telegram-on">Telegram alerts go to <strong>{who || `chat ${st.chat_id}`}</strong>{st.chat?.username && <> (@{st.chat.username})</>}
      {who && <> · chat {st.chat_id}</>}
      {st.bot && <> · <a href={`https://t.me/${st.bot}`} target="_blank" rel="noopener noreferrer" data-testid="telegram-chat">Open the chat</a> (@{st.bot})</>}
      {st.error && <span className="warn-text"> · couldn't reach Telegram: {st.error}</span>}</span>
  );
}

/** Settings > Notifications: the Telegram link (or how to set it up) and which pushes to send, saved as you click. */
export default function NotifyPage() {
  const [st, setSt] = useNotify();
  const [msg, setMsg] = useState("");
  /** Change some settings and save them at once. */
  const set = (patch) => {
    const prefs = { ...st.prefs, ...patch };
    setSt({ ...st, prefs }); setMsg("");
    api.put("/notify/prefs", prefs).then((p) => { setSt((s) => ({ ...s, prefs: p })); setMsg("Saved"); }).catch((e) => setMsg(e.message));
  };
  return (
    <div className="panel" data-testid="notify-settings">
      <h3>Telegram</h3>
      <p><TelegramLink st={st} /></p>
      {st && !st.configured && (
        <ol className="small muted notify-setup">
          <li>In Telegram, message <strong>@BotFather</strong>, send <code>/newbot</code> and copy the token. Message your new bot once, then open
            <code>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code> and copy <code>chat.id</code>.</li>
          <li>Create <code>backend/.env</code> with <code>TELEGRAM_BOT_TOKEN=…</code> and <code>TELEGRAM_CHAT_ID=…</code> (one per line).</li>
          <li>Restart the backend. Pushes go out while it runs; <code>python -m app.notify "hello"</code> tests delivery.</li>
        </ol>
      )}
      <h3>What to send</h3>
      {st?.prefs ? (
        <div className="notify-kinds">
          {KINDS.map(([k, label, when]) => (
            <label key={k} className="inline notify-kind"><input type="checkbox" checked={st.prefs[k]} onChange={(e) => set({ [k]: e.target.checked })} data-testid={`notify-${k}`} />
              <span><strong>{label}</strong> <span className="small muted">— {when}</span></span></label>
          ))}
          <label className="inline notify-wpa small">Lock calls only when locking adds at least
            <input type="number" min={0} max={100} step={1} value={st.prefs.lock_min_wpa} disabled={!st.prefs.lock}
              onChange={(e) => set({ lock_min_wpa: Math.max(0, Math.min(100, Math.round(Number(e.target.value) || 0))) })} data-testid="notify-lock-wpa" aria-label="Minimum win chance added" />
            points of win chance <span className="muted">(0 = every lock call; the card's WPA)</span></label>
        </div>
      ) : <div className="small muted">{st?.error || "Loading…"}</div>}
      {msg && <div className={`small ${msg === "Saved" ? "muted" : "warn-text"}`} data-testid="notify-msg">{msg}</div>}
    </div>
  );
}

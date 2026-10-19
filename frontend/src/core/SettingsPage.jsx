import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import useSaveShortcut from "../useSaveShortcut.js";

const SLOT_TYPES = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "BN", "IR"];
const BASE_KEYS = ["pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fg3m"];
const INJURY_STATUSES = ["healthy", "day_to_day", "out_short_term", "out_long_term", "out_season"];
const SLEEPER_RAW = ["DTD", "Out", "IR"];
const STATS = ["pts", "reb", "ast", "stl", "blk"];

function Num({ value, onChange, step = "any", ...rest }) {
  return <input type="number" step={step} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} {...rest} />;
}

const TIMEZONES = [
  ["America/New_York", "Eastern (ET)"], ["America/Chicago", "Central (CT)"], ["America/Denver", "Mountain (MT)"],
  ["America/Phoenix", "Arizona (MST)"], ["America/Los_Angeles", "Pacific (PT)"], ["America/Anchorage", "Alaska (AKT)"],
  ["Pacific/Honolulu", "Hawaii (HT)"], ["America/Toronto", "Toronto (ET)"], ["America/Vancouver", "Vancouver (PT)"],
  ["Europe/London", "London (UK)"], ["Europe/Berlin", "Central Europe (CET)"], ["Asia/Manila", "Manila (PHT)"],
  ["Asia/Tokyo", "Tokyo (JST)"], ["Australia/Sydney", "Sydney (AET)"],
];

export default function SettingsPage({ leagueId }) {
  const [s, setS] = useState(null);
  const [saved, setSaved] = useState(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [sleeperId, setSleeperId] = useState("");
  const [preview, setPreview] = useState(null);
  const [applyFields, setApplyFields] = useState({ name: false, scoring: true, roster_slots: true, num_managers: false, keepers: true });
  const [managers, setManagers] = useState([]);
  const loadManagers = useCallback(() => {
    if (leagueId) api.get(`/leagues/${leagueId}/managers`).then(setManagers).catch(() => setManagers([]));
  }, [leagueId]);
  useEffect(() => { loadManagers(); }, [loadManagers]);
  // which manager you are: saved at once (the PATCH un-marks everyone else)
  const markMe = (id) => api.patch(`/leagues/${leagueId}/managers/${id}`, { is_user: true }).then(() => { loadManagers(); setMsg("Saved: that manager is you."); }).catch((e) => setError(e.message));

  const load = useCallback(() => {
    if (!leagueId) return;
    api.get(`/leagues/${leagueId}/settings`).then((data) => { setS(data); setSaved(data); setSleeperId(data.sleeper_league_id || ""); }).catch((e) => setError(e.message));
  }, [leagueId]);
  useEffect(() => { load(); }, [load]);

  const dirty = s && saved && JSON.stringify(s) !== JSON.stringify(saved);

  const save = useCallback(async () => {
    if (!s) return;
    setMsg(""); setError("");
    try {
      const result = await api.put(`/leagues/${leagueId}/settings`, s);
      setS(result); setSaved(result);
      setMsg("Settings saved. Valuations recompute automatically when scoring changed.");
    } catch (e) {
      setError(e.message);
    }
  }, [leagueId, s]);
  useSaveShortcut(save, !!s);

  if (!leagueId) return <p className="muted">Select or create a league on the League tab first.</p>;
  if (!s) return <p>{error || "Loading…"}</p>;

  const set = (patch) => setS({ ...s, ...patch });
  const setDeep = (key, patch) => setS({ ...s, [key]: { ...s[key], ...patch } });
  const slotCount = (slot) => s.roster_slots.find((r) => r.slot === slot)?.count ?? 0;
  const setSlot = (slot, count) => {
    const others = s.roster_slots.filter((r) => r.slot !== slot);
    set({ roster_slots: count > 0 ? [...others, { slot, count }] : others });
  };
  const mandatory = s.roster_slots.filter((r) => r.slot !== "IR").reduce((a, r) => a + r.count, 0);

  const doPreview = async () => {
    setError(""); setPreview(null);
    try {
      setPreview(await api.post(`/leagues/${leagueId}/sleeper/preview`, { sleeper_league_id: sleeperId.trim() }));
    } catch (e) {
      setError(e.message);
    }
  };
  const doApply = async () => {
    setError("");
    try {
      const saved = await api.post(`/leagues/${leagueId}/sleeper/apply`, {
        sleeper_league_id: sleeperId.trim(), apply: Object.keys(applyFields).filter((k) => applyFields[k]),
      });
      setS(saved); setPreview(null);
      setMsg("Applied Sleeper league settings.");
    } catch (e) {
      setError(e.message);
    }
  };

  const bonus = s.scoring.bonuses;
  const setBonus = (i, patch) => setDeep("scoring", { bonuses: bonus.map((b, j) => (j === i ? { ...b, ...patch } : b)) });

  return (
    <div>
      <h2>League settings <span className="muted small">— every value is editable, before and during the draft</span></h2>
      <div className="row sticky-bar">
        <button className="primary" onClick={save} data-testid="settings-save">Save settings (Ctrl+S)</button>
        {dirty ? <span className="badge dirty" data-testid="settings-dirty">unsaved changes</span> : <span className="muted small">all changes saved</span>}
        {dirty && <button onClick={() => setS(saved)}>Discard</button>}
        {msg && <span className="ok">{msg}</span>}{error && <span className="error">{error}</span>}
      </div>

      <div className="panel">
        <h3>General</h3>
        <div className="grid3">
          <label>Name <input type="text" value={s.name} onChange={(e) => set({ name: e.target.value })} /></label>
          <label>Roster season <input type="text" value={s.roster_season} onChange={(e) => set({ roster_season: e.target.value })} /></label>
          <label>Stats season <input type="text" value={s.stats_season} onChange={(e) => set({ stats_season: e.target.value })} /></label>
          <label>Game mode <select value={s.game_mode} onChange={(e) => set({ game_mode: e.target.value })}><option value="lock_in">Lock-In</option><option value="standard">Standard</option></select>
            <span className="muted small">The Season tab works for Sleeper Lock-In leagues only (for now).</span></label>
          <label>Time zone <select value={s.timezone || "America/Chicago"} onChange={(e) => set({ timezone: e.target.value })} data-testid="timezone">
            {TIMEZONES.map(([z, label]) => <option key={z} value={z}>{label}</option>)}</select>
            <span className="muted small">Every in-season time (tips, alarms, news, the timeline) and when "today" ends.</span></label>
          <label>You are <select value={managers.find((m) => m.is_user)?.manager_id || ""} onChange={(e) => markMe(e.target.value)} data-testid="you-are">
            {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name}</option>)}</select>
            <span className="muted small">Your team: your side of the matchup, waivers, news. Saves at once.</span></label>
          <label>Player nicknames <select defaultValue={(() => { try { return localStorage.getItem("da.nicks") || "on"; } catch { return "on"; } })()}
              onChange={(e) => { try { localStorage.setItem("da.nicks", e.target.value); setMsg("Saved."); } catch { /* ignore */ } }} data-testid="nicks">
            <option value="on">Show</option><option value="off">Hide</option></select>
            <span className="muted small">The nicknames managers gave their players on Sleeper, under each name on the Season tab. Saves at once (this browser).</span></label>
          <label>Draft type <select value={s.draft_type} onChange={(e) => set({ draft_type: e.target.value })}><option value="auction">Auction</option><option value="snake">Snake</option></select></label>
          <label>Nomination order <select value={s.nomination_order_type} onChange={(e) => set({ nomination_order_type: e.target.value })}><option value="fixed_rotation">Fixed rotation</option><option value="snake">Snake</option></select></label>
          <label>Scoring format <select value={s.scoring_format} onChange={(e) => set({ scoring_format: e.target.value })}><option value="h2h_points">H2H points</option></select></label>
          <label>Budget per manager $<Num value={s.budget_per_manager} onChange={(v) => set({ budget_per_manager: v })} data-testid="budget" /></label>
          <label>Minimum bid $<Num value={s.min_bid} onChange={(v) => set({ min_bid: v })} /></label>
          <label>Bid increment $<Num value={s.bid_increment} onChange={(v) => set({ bid_increment: v })} /></label>
          <label>Managers <span className="muted">{s.num_managers} (edit on the League tab)</span></label>
        </div>
      </div>

      <div className="panel">
        <h3>Roster slots <span className="muted small">— {mandatory} mandatory (non-IR) slots must be filled by draft's end; IR is optional</span></h3>
        <div className="row">
          {SLOT_TYPES.map((slot) => <label key={slot} className="inline">{slot} <Num value={slotCount(slot)} onChange={(v) => setSlot(slot, v || 0)} step="1" data-testid={`slot-${slot}`} /></label>)}
        </div>
      </div>

      <div className="panel">
        <h3>Keepers</h3>
        <div className="row">
          <label className="inline"><input type="checkbox" checked={s.keeper.enabled} onChange={(e) => setDeep("keeper", { enabled: e.target.checked })} /> enabled</label>
          <label className="inline">max per manager <Num value={s.keeper.max_per_manager} onChange={(v) => setDeep("keeper", { max_per_manager: v })} step="1" data-testid="max-keepers" /></label>
          <label className="inline">deadline <input type="date" value={s.keeper.deadline || ""} onChange={(e) => setDeep("keeper", { deadline: e.target.value || null })} /></label>
        </div>
        <div className="row">
          <span>Keeper price rule: this year's price = last year's price</span>
          <label className="inline">+ $<Num value={s.keeper.escalation?.increase_per_step ?? 1} onChange={(v) => setDeep("keeper", { escalation: { ...s.keeper.escalation, increase_per_step: v ?? 0 } })} step="1" data-testid="esc-increase" /></label>
          <label className="inline">per full $<Num value={s.keeper.escalation?.step_dollars ?? 5} onChange={(v) => setDeep("keeper", { escalation: { ...s.keeper.escalation, step_dollars: v ?? 1 } })} step="1" data-testid="esc-step" /></label>
          <label className="inline"><input type="checkbox" checked={s.keeper.escalation?.enabled ?? true} onChange={(e) => setDeep("keeper", { escalation: { ...s.keeper.escalation, enabled: e.target.checked } })} /> enabled</label>
          <span className="muted small">(e.g. $17 → ${(s.keeper.escalation?.enabled ?? true) ? 17 + (s.keeper.escalation?.increase_per_step ?? 1) * Math.floor(17 / Math.max(1, s.keeper.escalation?.step_dollars ?? 5)) : 17})</span>
        </div>
      </div>

      <div className="panel">
        <h3>Scoring — base values per stat <span className="badge">{s.scoring.source}</span></h3>
        <div className="row">
          {BASE_KEYS.map((k) => <label key={k} className="inline">{k} <Num value={s.scoring.base[k]} onChange={(v) => setDeep("scoring", { base: { ...s.scoring.base, [k]: v ?? 0 } })} data-testid={`base-${k}`} /></label>)}
        </div>
        <h3>Per-game bonuses <span className="muted small">(stack; triggered by a single game's line)</span></h3>
        <table>
          <thead><tr><th>id</th><th>kind</th><th>stat</th><th>threshold</th><th>bonus</th><th></th></tr></thead>
          <tbody>
            {bonus.map((b, i) => (
              <tr key={i}>
                <td><input type="text" value={b.id} onChange={(e) => setBonus(i, { id: e.target.value })} style={{ width: 110 }} /></td>
                <td><select value={b.kind} onChange={(e) => setBonus(i, { kind: e.target.value })}><option value="stat_threshold">stat threshold</option><option value="triple_double">triple-double</option></select></td>
                <td>{b.kind === "stat_threshold" && <select value={b.stat || "pts"} onChange={(e) => setBonus(i, { stat: e.target.value })}>{STATS.map((x) => <option key={x}>{x}</option>)}</select>}</td>
                <td>{b.kind === "stat_threshold" && <Num value={b.threshold} onChange={(v) => setBonus(i, { threshold: v })} step="1" />}</td>
                <td><Num value={b.bonus} onChange={(v) => setBonus(i, { bonus: v ?? 0 })} data-testid={`bonus-${b.id}`} /></td>
                <td><button className="danger" onClick={() => setDeep("scoring", { bonuses: bonus.filter((_, j) => j !== i) })}>remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <button onClick={() => setDeep("scoring", { bonuses: [...bonus, { id: `bonus_${bonus.length + 1}`, kind: "stat_threshold", stat: "pts", threshold: 30, bonus: 1 }] })}>Add bonus rule</button>
      </div>

      <div className="panel">
        <h3>Ranking</h3>
        <div className="small muted">Value = weight avg × FP/G + weight ceiling × ceiling, × games confidence × injury × age × availability. FP/G blends Sleeper's season projection with last season (projection weight). All in fantasy points under the scoring above.</div>
        <div className="row">
          <label className="inline">weight avg (FP/G) <Num value={s.ranking.weight_avg} onChange={(v) => setDeep("ranking", { weight_avg: v })} /></label>
          <label className="inline">weight ceiling <Num value={s.ranking.weight_ceiling} onChange={(v) => setDeep("ranking", { weight_ceiling: v })} /></label>
          <label className="inline">ceiling =
            <select value={s.ranking.ceiling_metric || "weekly_best"} onChange={(e) => setDeep("ranking", { ceiling_metric: e.target.value })} data-testid="ceiling-metric">
              <option value="weekly_best">average of each week's best game (Lock-In)</option>
              <option value="top_quarter">average of the top 25% of games</option>
              <option value="best_game">single best game (noisy)</option>
            </select>
          </label>
        </div>
        <div className="row">
          <label className="inline" title="share of FP/G from Sleeper's season projection (role, minutes, new team); the rest is last season">projection weight (0–1) <Num value={s.ranking.projection_weight ?? 1} onChange={(v) => setDeep("ranking", { projection_weight: v ?? 0 })} data-testid="projection-weight" /></label>
          <label className="inline" title="bench spots per team that get real auction money; the rest are $1 fills">priced bench spots <Num value={s.ranking.priced_bench_slots ?? 2} onChange={(v) => setDeep("ranking", { priced_bench_slots: v ?? 0 })} step="1" data-testid="priced-bench" /></label>
          <label className="inline">min games for full confidence <Num value={s.ranking.min_games_full_confidence} onChange={(v) => setDeep("ranking", { min_games_full_confidence: v })} step="1" /></label>
          <label className="inline">availability weight (0 = ignore missed weeks, 1 = scale fully) <Num value={s.ranking.availability_weight ?? 0} onChange={(v) => setDeep("ranking", { availability_weight: v ?? 0 })} data-testid="availability-weight" /></label>
          <label className="inline" title="Lock-In: more games in a week = more shots at a big night; fantasy playoff weeks count double">schedule weight (0 = off, 1 = full) <Num value={s.ranking.schedule_weight ?? 1} onChange={(v) => setDeep("ranking", { schedule_weight: v ?? 0 })} data-testid="schedule-weight" /></label>
          <label className="inline" title="value measured against the replacement player at the scarcest position the player can fill">position scarcity weight (0 = off, 1 = full) <Num value={s.ranking.scarcity_weight ?? 1} onChange={(v) => setDeep("ranking", { scarcity_weight: v ?? 0 })} data-testid="scarcity-weight" /></label>
          <label className="inline"><input type="checkbox" checked={s.ranking.hide_unrosterable} onChange={(e) => setDeep("ranking", { hide_unrosterable: e.target.checked })} /> hide players I cannot roster</label>
        </div>
        <div className="row">
          <span>Injury multipliers:</span>
          {INJURY_STATUSES.map((k) => <label key={k} className="inline">{k} <Num value={s.ranking.injury_multipliers[k]} onChange={(v) => setDeep("ranking", { injury_multipliers: { ...s.ranking.injury_multipliers, [k]: v ?? 1 } })} /></label>)}
        </div>
        <div className="row">
          <span>Sleeper injury seed map:</span>
          {SLEEPER_RAW.map((k) => (
            <label key={k} className="inline">{k} → <select value={s.ranking.sleeper_injury_map[k] || "day_to_day"} onChange={(e) => setDeep("ranking", { sleeper_injury_map: { ...s.ranking.sleeper_injury_map, [k]: e.target.value } })}>{INJURY_STATUSES.map((x) => <option key={x}>{x}</option>)}</select></label>
          ))}
        </div>
        <div className="row">
          <label className="inline">age penalty starts at <Num value={s.ranking.age_penalty_start} onChange={(v) => setDeep("ranking", { age_penalty_start: v })} step="1" /></label>
          <label className="inline">per year <Num value={s.ranking.age_penalty_per_year} onChange={(v) => setDeep("ranking", { age_penalty_per_year: v })} /></label>
          <label className="inline">max <Num value={s.ranking.age_penalty_max} onChange={(v) => setDeep("ranking", { age_penalty_max: v })} /></label>
        </div>
      </div>

      <div className="panel">
        <h3>Sleeper league (optional) <span className="muted small">— pulls the live league's scoring and roster</span></h3>
        <div className="row">
          <input type="text" placeholder="sleeper league id" value={sleeperId} onChange={(e) => setSleeperId(e.target.value)} data-testid="sleeper-league-id" />
          <button onClick={doPreview} disabled={!sleeperId.trim()} data-testid="sleeper-preview">Preview</button>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <label className="inline small" title="used by the data pull for managers, keepers, last year's auction, and by live draft sync">linked league
            <input type="text" value={s.sleeper_league_id || ""} placeholder="none" onChange={(e) => set({ sleeper_league_id: e.target.value.trim() || null })} data-testid="linked-sleeper-league" />
          </label>
          <label className="inline small" title="leave empty to sync the league's own draft; paste a Sleeper mock draft id (from sleeper.com/draft/nba/<id>) to test sync">sync draft id
            <input type="text" value={s.sleeper_draft_id || ""} placeholder="league's draft" onChange={(e) => set({ sleeper_draft_id: e.target.value.trim() || null })} data-testid="sleeper-draft-id" />
          </label>
          <label className="inline small" title="other Sleeper leagues with the same people (dynasty, old seasons, any format): used only to learn favourite teams, young/veteran lean and who drafted whom">history leagues
            <input type="text" key={(s.sleeper_history_league_ids || []).join(",")} defaultValue={(s.sleeper_history_league_ids || []).join(", ")} placeholder="ids, comma-separated" onBlur={(e) => set({ sleeper_history_league_ids: e.target.value.split(/[\s,]+/).filter(Boolean) })} data-testid="sleeper-history-ids" style={{ minWidth: 260 }} />
          </label>
          <span className="small muted">Save, then pull data (top of this page) to fetch managers, keepers and past drafts.</span>
        </div>
        {preview && (
          <div>
            <p className="small">{preview.league.name} · {preview.league.sport} · season {preview.league.season} · {preview.league.total_rosters} rosters · status {preview.league.status}</p>
            <p className="small">Unknown keys: {preview.scoring_map.unknown_keys.join(", ") || "none"} · unsupported non-zero: {JSON.stringify(preview.scoring_map.unsupported_nonzero)} · missing expected: {preview.scoring_map.missing_expected.join(", ") || "none"}</p>
            <table>
              <thead><tr><th>field</th><th>current</th><th>Sleeper</th></tr></thead>
              <tbody>
                {preview.diffs.length === 0 && <tr><td colSpan="3" className="ok">No differences from the current settings.</td></tr>}
                {preview.diffs.map((d, i) => <tr key={i}><td>{d.field}</td><td><code>{JSON.stringify(d.current)}</code></td><td><code>{JSON.stringify(d.sleeper)}</code></td></tr>)}
              </tbody>
            </table>
            <div className="row">
              Apply:
              {Object.keys(applyFields).map((k) => <label key={k} className="inline"><input type="checkbox" checked={applyFields[k]} onChange={(e) => setApplyFields({ ...applyFields, [k]: e.target.checked })} /> {k}</label>)}
              <button className="primary" onClick={doApply} data-testid="sleeper-apply">Apply selected</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

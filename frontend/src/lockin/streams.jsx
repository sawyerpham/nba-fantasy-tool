// NBA streams: one redirect per game, looked up on streamed.pk. The match list is free and needs no key.
// The URL is never built from team names. The ids in it are upstream ids the site assigns, and its slugs are
// irregular ("philadelphia-76-ers", "atl-tico-madrid", "vf-b-stuttgart"), so a guessed link is a dead page.
import { useEffect, useState } from "react";

const API = "https://streamed.pk";
const TTL = 5 * 60000;      // the match list changes slowly
const NEAR = 36 * 3600e3;   // a listed game counts for a slate day if its tip is within a day and a half

// Sleeper team id -> how the stream site spells it. Extra keys are other spellings in use.
const NBA = {
  ATL: ["Atlanta Hawks"], BOS: ["Boston Celtics"], BKN: ["Brooklyn Nets"], BRK: ["Brooklyn Nets"],
  CHA: ["Charlotte Hornets"], CHO: ["Charlotte Hornets"], CHI: ["Chicago Bulls"],
  CLE: ["Cleveland Cavaliers"], DAL: ["Dallas Mavericks"], DEN: ["Denver Nuggets"],
  DET: ["Detroit Pistons"], GSW: ["Golden State Warriors"], GS: ["Golden State Warriors"],
  HOU: ["Houston Rockets"], IND: ["Indiana Pacers"],
  LAC: ["LA Clippers", "Los Angeles Clippers"], LAL: ["Los Angeles Lakers"],
  MEM: ["Memphis Grizzlies"], MIA: ["Miami Heat"], MIL: ["Milwaukee Bucks"],
  MIN: ["Minnesota Timberwolves"], NOP: ["New Orleans Pelicans"], NO: ["New Orleans Pelicans"],
  NYK: ["New York Knicks"], OKC: ["Oklahoma City Thunder"], ORL: ["Orlando Magic"],
  PHI: ["Philadelphia 76ers", "Philadelphia Sixers"], PHX: ["Phoenix Suns"], PHO: ["Phoenix Suns"],
  POR: ["Portland Trail Blazers", "Portland Trailblazers"], SAC: ["Sacramento Kings"],
  SAS: ["San Antonio Spurs"], TOR: ["Toronto Raptors"], UTA: ["Utah Jazz"], UTH: ["Utah Jazz"],
  WAS: ["Washington Wizards"],
};

const norm = (s) => String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

const alias = (team) => {
  const k = String(team || "").toUpperCase();
  return (NBA[k] || [team]).filter(Boolean).map(norm);
};

// Does one side of a listed match name this team? Exact, or one spelling contains the other.
function isTeam(side, team) {
  const s = norm(side);
  if (!s) return false;
  return alias(team).some((w) => w && (s === w || s.includes(w) || (s.length >= 4 && w.includes(s))));
}

const iso = (ms, tz) => new Intl.DateTimeFormat("en-CA", {
  timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date(ms));   // "2026-10-20"

export function findMatch(list, game, team, tz) {
  if (!game || !team) return null;
  const hits = (list || []).filter((m) => {
    const h = m?.teams?.home?.name, a = m?.teams?.away?.name;
    if (!h || !a || !m.date) return false;
    if (tz && iso(m.date, tz) !== game.date) return false;
    return (isTeam(h, team) && isTeam(a, game.opp)) || (isTeam(h, game.opp) && isTeam(a, team));
  });
  const near = (m) => Math.abs(m.date - (Date.parse(`${game.date}T12:00:00`) || 0));
  return hits.sort((x, y) => near(x) - near(y))[0] || null;
}

// The watch page is /watch/{match id}/{source}/{stream number}. Stream 1 is the first one listed. No match (the list
// didn't load: streamed.pk's API now redirects to its homepage, or the game isn't listed yet): the site's homepage,
// so the Watch button is always there.
export function watchUrl(m) {
  const src = m?.sources?.[0];
  return src ? `${API}/watch/${m.id}/${src.source}/1` : `${API}/`;
}

// The frame instead, if you ever want the player on your own page. One small request for the stream number.
export async function embedUrl(m) {
  const src = m?.sources?.[0];
  if (!src) return null;
  const r = await fetch(`${API}/api/stream/${src.source}/${src.id}`);
  if (!r.ok) return null;
  const list = await r.json();
  return list?.[0]?.embedUrl || null;
}

let cache = { at: 0, list: [], error: "" };
let inflight = null;
let timer = null;
const subs = new Set();

function publish(next) { cache = next; for (const f of subs) f(cache); }

function refresh() {
  if (Date.now() - cache.at < TTL || inflight) return;
  inflight = fetch(`${API}/api/matches/basketball`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`streamed.pk ${r.status}`))))
    .then((list) => publish({ at: Date.now(), list: Array.isArray(list) ? list : [], error: "" }))
    .catch((e) => publish({ ...cache, error: e.message }))
    .finally(() => { inflight = null; });
}

// One request and one timer for the whole page, however many cards ask.
export function useNBAMatches() {
  const [state, setState] = useState(cache);
  useEffect(() => {
    subs.add(setState);
    refresh();
    if (!timer) timer = setInterval(refresh, TTL);
    return () => { subs.delete(setState); };
  }, []);
  return state;
}
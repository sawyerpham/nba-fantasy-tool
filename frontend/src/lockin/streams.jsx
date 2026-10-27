// NBA streams for ppv.st. One link per game. The index is public and needs no key.
// The watch page is https://ppv.st/live/{uri_name} and that uri_name is assigned upstream.
// Its slugs are irregular, so a link built from team names is a dead page.
// Every event leaks the two team codes three ways, in the uri slug, in the poster filename
// and in the spelled out name. Any one of the three is enough for a match.
import { useEffect, useState } from "react";

const SITE = "https://ppv.st";
const PRIMARY = "ppv.st";
const TTL = 60 * 1000;        // the docs ask for about one poll a minute
const PING_TTL = 10 * 60000;  // the mirror list changes rarely
const NEAR = 36 * 3600e3;     // a listed game counts for a slate day if its tip is within a day and a half

// Sleeper team id -> how the site spells it. Extra keys are other ids in use.
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

// Sleeper id -> the code the site writes into its slugs and poster names. Only the odd ids differ.
const CODE = {
  BRK: ["BKN"], BKN: ["BKN"], CHO: ["CHA"], CHA: ["CHA"], GS: ["GSW"], GSW: ["GSW"],
  NO: ["NOP"], NOP: ["NOP"], PHO: ["PHX"], PHX: ["PHX"], UTH: ["UTA"], UTA: ["UTA"],
};

const norm = (s) => String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

const alias = (team) => {
  const k = String(team || "").toUpperCase();
  return (NBA[k] || [team]).filter(Boolean).map(norm);
};

// Every code a team can appear as. Two letter ids are dropped because the alt code covers them.
function codes(team) {
  const k = String(team || "").toUpperCase().trim();
  const out = new Set(k ? [k.toLowerCase()] : []);
  for (const c of CODE[k] || []) out.add(c.toLowerCase());
  return [...out].filter((c) => c.length >= 3);
}

// Does one side of a listed name spell this team? Exact, or one spelling holds the other.
function isTeam(side, team) {
  const s = norm(side);
  if (!s) return false;
  return alias(team).some((w) => w && (s === w || s.includes(w) || (s.length >= 4 && w.includes(s))));
}

// Do a pair of codes name the two teams of this game? Order is irrelevant.
function pairHit(tokens, team, opp) {
  if (!Array.isArray(tokens) || !tokens.length) return false;
  const set = new Set(tokens.map((x) => String(x).toLowerCase()));
  const mine = codes(team);
  const theirs = codes(opp);
  if (!mine.length || !theirs.length) return false;
  return mine.some((c) => set.has(c)) && theirs.some((c) => set.has(c));
}

// The last piece of a uri_name, as in nba-reg/week-8/nop-ind giving nop and ind.
function slugTokens(m) {
  const seg = String(m?.uri || "").split("/").filter(Boolean).pop() || "";
  return seg.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

// The pair inside the poster filename, as in nop-@-ind-12_15_2024-game-card.png
function posterTokens(m) {
  const hit = String(m?.poster || "").match(/([a-z]{2,4})-@-([a-z]{2,4})/i);
  return hit ? [hit[1].toLowerCase(), hit[2].toLowerCase()] : [];
}

// "Pelicans at Pacers" and "Carolina Panthers vs Green Bay Packers" both split into two sides.
function nameSides(m) {
  const parts = String(m?.name || "").split(/\s+(?:at|vs\.?|v\.?|@)\s+/i).map((s) => s.trim());
  return parts.length === 2 && parts[0] && parts[1] ? parts : null;
}

export function sameGame(m, team, opp) {
  if (!m) return false;
  if (pairHit(slugTokens(m), team, opp)) return true;
  if (pairHit(posterTokens(m), team, opp)) return true;
  const sides = nameSides(m);
  if (!sides) return false;
  return (isTeam(sides[0], team) && isTeam(sides[1], opp))
    || (isTeam(sides[0], opp) && isTeam(sides[1], team));
}

const iso = (ms, tz) => new Intl.DateTimeFormat("en-CA", {
  timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date(ms));   // "2026-10-20"

export function findMatch(list, game, team, tz) {
  if (!game || !team) return null;
  const day = String(game.date || "");
  const hits = (list || []).filter((m) => {
    if (!m?.uri || !m.startsAt) return false;   // 24/7 channels carry no tip time
    if (tz && day && iso(m.startsAt, tz) !== day) return false;
    return sameGame(m, team, game.opp);
  });
  const target = Date.parse(`${day}T12:00:00`) || 0;
  const near = (m) => Math.abs(m.startsAt - target);
  return hits.filter((m) => !target || near(m) <= NEAR).sort((x, y) => near(x) - near(y))[0] || null;
}

// The watch page is https://ppv.st/live/{uri_name}. No match, or a list that never loaded, falls
// back to the homepage, so the Watch button is always there.
export function watchUrl(m) {
  const uri = String(m?.uri || "").trim();
  return uri ? `${SITE}/live/${uri}` : `${SITE}/`;
}

// The embed rides along in the index payload, so no second request is needed. Most cards carry a
// plain URL, some carry a whole tag, a few carry nothing at all. Render it as given, with no
// sandbox attribute, because the site rules forbid changing embed behaviour.
export async function embedUrl(m) {
  const raw = String(m?.iframe || (m?.substreams || []).find((s) => s?.iframe)?.iframe || "").trim();
  if (!raw) return null;
  const src = raw.match(/src\s*=\s*["']([^"']+)["']/i);
  if (src) return src[1];
  return /^https?:\/\//i.test(raw) ? raw : null;
}

let cache = { at: 0, list: [], error: "" };
let hosts = { at: 0, list: [] };
let inflight = null;
let timer = null;
const subs = new Set();

function publish(next) { cache = next; for (const f of subs) f(cache); }

// Mirror order comes from the ping endpoint. The bare site host has no ping route, only the api
// subdomain answers.
async function apiHosts() {
  if (Date.now() - hosts.at < PING_TTL && hosts.list.length) return hosts.list;
  let list = [];
  try {
    const r = await fetch(`https://api.${PRIMARY}/api/ping`);
    if (r.ok) {
      const data = await r.json();
      list = (data?.domains || []).filter((d) => typeof d === "string" && d.includes("."));
    }
  } catch {
    /* fall through to the primary */
  }
  if (!list.length) list = [PRIMARY];
  hosts = { at: Date.now(), list };
  return list;
}

// Categories hold the streams, so flatten once and keep the fields a card needs.
function flatten(cats) {
  const out = [];
  for (const cat of cats || []) {
    const category = String(cat?.category || cat?.category_name || "");
    for (const s of cat?.streams || []) {
      const uri = String(s?.uri_name || "").trim();
      if (!uri) continue;
      out.push({
        id: s?.id,
        uri,
        name: String(s?.name || "").trim(),
        category,
        tag: String(s?.tag || ""),
        poster: String(s?.poster || ""),
        startsAt: Number(s?.starts_at || 0) * 1000,
        endsAt: Number(s?.ends_at || 0) * 1000,
        alwaysLive: !!Number(s?.always_live || 0),
        iframe: s?.iframe || "",
        substreams: Array.isArray(s?.substreams) ? s.substreams : [],
      });
    }
  }
  return out;
}

async function fetchIndex() {
  let lastErr = "ppv.st index unavailable";
  for (const host of await apiHosts()) {
    try {
      const r = await fetch(`https://api.${host}/api/streams`);
      if (!r.ok) { lastErr = `ppv.st ${r.status}`; continue; }
      const data = await r.json();
      if (!data?.success || !Array.isArray(data.streams)) {
        lastErr = data?.error || "unexpected payload";
        continue;
      }
      return flatten(data.streams);
    } catch (e) {
      lastErr = e?.message || lastErr;
    }
  }
  throw new Error(lastErr);
}

function refresh() {
  if (Date.now() - cache.at < TTL || inflight) return;
  inflight = fetchIndex()
    .then((list) => publish({ at: Date.now(), list, error: "" }))
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
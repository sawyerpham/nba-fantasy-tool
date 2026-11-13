import React, { useEffect, useState } from "react";
import { CANADA, MAP_H, MAP_W, OUTLINE, PINS, STATES } from "./mapData.js";

const LOGO = 30, IMG = 22;   // IMG: the logo inside its disc; bigger spills out of the circle for full-bleed logos (Pacers, Bulls)
/** Logo offset (dx, dy) from the true location, for teams that share a metro or sit too close; a leader line joins them. */
const NUDGE = {
  NYK: [-6, -36], BKN: [40, 8], PHI: [30, 24], MIL: [-8, -26], CHI: [-16, 14], DET: [-6, -22], CLE: [18, 12],
  GSW: [-28, 14], SAC: [22, -28], LAL: [-26, 24], LAC: [28, 26],
};
const ABBRS = Object.keys(PINS);
const logo = (a) => `https://sleepercdn.com/images/team_logos/nba/${a.toLowerCase()}.png`;
/** Curved path between two pins, bowed upward like a flight arc. */
const arc = ([x1, y1], [x2, y2]) => `M${x1},${y1} Q${(x1 + x2) / 2},${(y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.3} ${x2},${y2}`;

/** Black-and-white map of the lower 48 plus southern Canada, one logo pin per NBA team, with a random arc "game" flying between two teams every few seconds. */
export default function TeamMap() {
  const [game, setGame] = useState(null);
  useEffect(() => {
    let n = 0;
    const tick = () => {
      const a = ABBRS[Math.floor(Math.random() * ABBRS.length)];
      let b = a;
      while (b === a) b = ABBRS[Math.floor(Math.random() * ABBRS.length)];
      setGame({ a, b, n: n++ });
    };
    tick();
    const id = setInterval(tick, 2600);
    return () => clearInterval(id);
  }, []);
  return (
    <svg className="teammap" viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img" aria-label="Map of NBA team locations" data-testid="team-map">
      <path className="tm-canada" d={CANADA} pathLength="1" />
      <path className="tm-state" d={STATES} pathLength="1" />
      <path className="tm-outline" d={OUTLINE} pathLength="1" />
      {game && <path key={game.n} className="tm-arc" d={arc(PINS[game.a], PINS[game.b])} pathLength="1" />}
      {ABBRS.map((a, i) => {
        const [x, y] = PINS[a], [dx, dy] = NUDGE[a] || [0, 0];
        return (
          <g key={a} className={`tm-pin ${game && (game.a === a || game.b === a) ? "hot" : ""}`} style={{ "--d": `${1.2 + i * 0.06}s` }}>
            {(dx || dy) && <line x1={x} y1={y} x2={x + dx} y2={y + dy} className="tm-lead" />}
            <circle cx={x} cy={y} r="2.5" className="tm-dot" />
            <circle cx={x + dx} cy={y + dy} r={LOGO / 2 + 2} className="tm-ring" />
            <circle cx={x + dx} cy={y + dy} r={LOGO / 2 + 2} className="tm-disc" />
            <image href={logo(a)} x={x + dx - IMG / 2} y={y + dy - IMG / 2} width={IMG} height={IMG} />
            <title>{a}</title>
          </g>
        );
      })}
    </svg>
  );
}

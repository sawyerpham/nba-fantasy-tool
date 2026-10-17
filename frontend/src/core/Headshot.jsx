import React, { useState } from "react";

// Sleeper's public headshot for a player (same ids as the Sleeper API). Fixed size so nothing shifts while it
// loads; initials when there is no photo.
export default function Headshot({ sleeperId, name = "", size = 32 }) {
  const [failed, setFailed] = useState(false);
  const initials = name.split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("");
  const style = { width: size, height: size, fontSize: Math.round(size * 0.38) };
  if (!sleeperId || failed) return <span className="headshot fallback" style={style} aria-hidden="true">{initials}</span>;
  return (
    <img
      className="headshot" style={style} width={size} height={size} loading="lazy" alt=""
      src={`https://sleepercdn.com/content/nba/players/thumb/${sleeperId}.jpg`} onError={() => setFailed(true)}
    />
  );
}

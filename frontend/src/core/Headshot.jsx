import React, { useState } from "react";

/**
 * A player's Sleeper headshot (same ids as the Sleeper API) at a fixed size, so nothing shifts while it loads.
 * Falls back to the player's initials when there is no photo or it fails to load.
 * `large` asks for Sleeper's full-size image, for sizes past a thumbnail.
 */
export default function Headshot({ sleeperId, name = "", size = 32, large = false }) {
  const [failed, setFailed] = useState(false);
  const initials = name.split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("");
  const style = { width: size, height: size, fontSize: Math.round(size * 0.38) };
  if (!sleeperId || failed) return <span className="headshot fallback" style={style} aria-hidden="true">{initials}</span>;
  return (
    <img
      className="headshot" style={style} width={size} height={size} loading="lazy" alt=""
      src={`https://sleepercdn.com/content/nba/players/${large ? "" : "thumb/"}${sleeperId}.jpg`} onError={() => setFailed(true)}
    />
  );
}

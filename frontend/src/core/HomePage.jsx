import React from "react";
import TeamMap from "./TeamMap.jsx";

/** Landing page: the title over an animated map of every NBA team, filling the screen. */
export default function HomePage() {
  return (
    <div className="home" data-testid="home-page">
      <h1>NBA Fantasy Tool</h1>
      <TeamMap />
    </div>
  );
}

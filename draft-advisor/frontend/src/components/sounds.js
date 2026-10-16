// Draft alerts made in the browser (Web Audio, no sound files). Browsers allow sound once you've clicked the page.
let ctx = null;

function play(notes, type, peak) {
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const t = ctx.currentTime;
    notes.forEach(([hz, at, len]) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type; o.frequency.value = hz;
      g.gain.setValueAtTime(0.0001, t + at);
      g.gain.exponentialRampToValueAtTime(peak, t + at + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + at + len);
      o.connect(g).connect(ctx.destination); o.start(t + at); o.stop(t + at + len + 0.02);
    });
  } catch { /* no audio: the blink still shows it */ }
}

// New high bid: a quick, high two-note chime.
export const bidSound = () => play([[880, 0, 0.18], [1320, 0.09, 0.18]], "sine", 0.25);
// New player nominated: a lower, longer three-note rise, so you can tell it apart without looking.
export const nominationSound = () => play([[523, 0, 0.3], [659, 0.16, 0.3], [784, 0.32, 0.5]], "triangle", 0.3);
// Swap / GTD alarm: an urgent repeated two-tone, distinct from the draft sounds.
export const alarmSound = () => play([[988, 0, 0.16], [740, 0.18, 0.16], [988, 0.36, 0.16], [740, 0.54, 0.16], [988, 0.72, 0.3]], "square", 0.18);

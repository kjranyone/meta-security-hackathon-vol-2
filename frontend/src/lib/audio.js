// 大イベント演出音（WebAudio。ユーザー操作後に初期化、🔇でミュート）
let ac = null;

export function initAudio() {
  if (!ac) {
    try { ac = new (window.AudioContext || window.webkitAudioContext)(); }
    catch { /* WebAudio unavailable */ }
  }
  if (ac && ac.state === "suspended") ac.resume();
}

export function beep(freq = 330, type = "sawtooth", gain = 0.12) {
  if (!ac) return;
  const o = ac.createOscillator(), g = ac.createGain();
  o.type = type;
  o.frequency.value = freq;
  g.gain.setValueAtTime(0.001, ac.currentTime);
  g.gain.exponentialRampToValueAtTime(gain, ac.currentTime + 0.02);
  g.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.5);
  o.connect(g).connect(ac.destination);
  o.start(); o.stop(ac.currentTime + 0.5);
}

// イベント種別 → 音程
export const MAJOR_TONES = {
  sovereign_default: 220, war_start: 110, collapse: 165,
  price_spike: 440, god_intervention: 660, crash: 195,
};
export const MAJOR_COLOR = {
  sovereign_default: "#ff6b35", war_start: "#f85149", collapse: "#d29922",
  price_spike: "#e3b341", god_intervention: "#a371f7", crash: "#e5534b",
};

export function toneForTypes(types) {
  const freqs = types.map(t => MAJOR_TONES[t]).filter(Boolean);
  return freqs.length ? Math.min(...freqs) : 330;
}

const COLOR_TO_TYPE = Object.fromEntries(
  Object.entries(MAJOR_TONES).map(([t, f]) => [MAJOR_COLOR[t], t]));
export function toneForColor(color) {
  return MAJOR_TONES[COLOR_TO_TYPE[color]] || 330;
}

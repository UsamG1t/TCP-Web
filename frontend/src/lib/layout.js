// Shared horizontal layout so the ladder and the window chart share an x-axis.
export const PAD_L = 64;
export const PAD_R = 18;

export function makeX(width, tEnd) {
  const t = Math.max(tEnd, 1);
  const w = Math.max(width - PAD_L - PAD_R, 1);
  return (time) => PAD_L + (time / t) * w;
}

export function niceStep(tEnd) {
  const raw = Math.max(tEnd, 1) / 10;
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  for (const m of [1, 2, 5, 10]) if (pow * m >= raw) return pow * m;
  return pow * 10;
}

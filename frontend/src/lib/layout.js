/**
 * Shared horizontal layout for the time-based views.
 *
 * The ladder diagram and the window chart are separate components stacked one
 * above the other, and the whole point of that arrangement is that a loss on the
 * ladder lines up vertically with the dip it causes in the congestion window.
 * That only holds if both map time to pixels identically, so the mapping lives
 * here rather than in either component.
 */

/**
 * Left padding in pixels, reserved for the lane and axis labels.
 * @type {number}
 */
export const PAD_L = 64;

/**
 * Right padding in pixels, so the final events do not touch the edge.
 * @type {number}
 */
export const PAD_R = 18;

/**
 * Build a function mapping virtual time to a horizontal pixel position.
 *
 * The whole trace is fitted to the available width, so the scale changes as the
 * trace grows or the window is resized. Both the lower bounds guard against
 * division by zero on an empty trace or a component that has not been measured
 * yet — either would otherwise produce `NaN` coordinates and an invisible SVG.
 *
 * @param {number} width Full component width in pixels, padding included.
 * @param {number} tEnd Virtual time at the end of the trace, in milliseconds.
 * @returns {function(number): number} Converts a timestamp to an x coordinate.
 */
export function makeX(width, tEnd) {
  const t = Math.max(tEnd, 1);
  const w = Math.max(width - PAD_L - PAD_R, 1);
  return (time) => PAD_L + (time / t) * w;
}

/**
 * Choose a round interval between grid lines.
 *
 * Aims for roughly ten divisions, then rounds up to the next 1, 2 or 5 times a
 * power of ten — the intervals people read comfortably. Without the rounding a
 * grid line would land on values like 1237 ms and the axis would be unreadable.
 *
 * @param {number} tEnd Virtual time at the end of the trace, in milliseconds.
 * @returns {number} Interval between grid lines, in milliseconds.
 */
export function niceStep(tEnd) {
  const raw = Math.max(tEnd, 1) / 10;
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  for (const m of [1, 2, 5, 10]) if (pow * m >= raw) return pow * m;
  return pow * 10;
}

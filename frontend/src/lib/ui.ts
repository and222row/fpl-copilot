/**
 * Shared sizing for the small controls scattered across the dashboard.
 *
 * A 36px-tall target is the default — comfortable for a thumb without the
 * buttons looking oversized. It shrinks to the compact 28px chrome the desktop
 * layout was designed around only when the screen is wide *and* the pointer is
 * precise, so a touch tablet keeps the big targets even at 800px. Centralised
 * because the dashboard has around twenty of these and they must stay
 * visually identical.
 */
const SIZE =
  "min-h-9 rounded-md whitespace-nowrap px-3 text-xs font-semibold " +
  "transition sm:pointer-fine:min-h-7";

/** Buttons centre their label; selects are left alone so the native
 *  control renders its text and chevron the way the platform expects. */
const BTN = `inline-flex shrink-0 items-center justify-center ${SIZE}`;

export const BTN_PRIMARY =
  `${BTN} bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50 ` +
  "dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white";

export const BTN_SECONDARY =
  `${BTN} border border-slate-300 text-slate-600 hover:bg-slate-100 ` +
  "disabled:opacity-50 dark:border-slate-600 dark:text-slate-400 " +
  "dark:hover:bg-slate-800";

export const SELECT =
  `${SIZE} border border-slate-300 bg-white text-slate-700 ` +
  "dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300";

/** Segmented control: a bordered strip of mutually exclusive buttons. */
export const SEGMENT_GROUP =
  "flex shrink-0 rounded-md border border-slate-300 dark:border-slate-600";

export const SEGMENT_BASE =
  "inline-flex min-h-9 items-center whitespace-nowrap px-2.5 text-xs " +
  "font-semibold transition first:rounded-l-md last:rounded-r-md " +
  "sm:pointer-fine:min-h-7";

export const SEGMENT_ON =
  "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900";

export const SEGMENT_OFF =
  "text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800";

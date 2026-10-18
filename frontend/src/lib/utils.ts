/**
 * Lightweight className helper for composing Tailwind classes.
 */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

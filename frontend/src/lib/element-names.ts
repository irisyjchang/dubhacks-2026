type Element = { name?: string; code?: string; kind?: string };

const rotations: Record<string, string> = { 1: "Single", 2: "Double", 3: "Triple", 4: "Quadruple", 5: "Quintuple" };
const jumps: Record<string, string> = { A: "Axel", T: "Toe Loop", S: "Salchow", Lo: "Loop", F: "Flip", Lz: "Lutz" };

/** Expand judging shorthand without turning spins or sequences into jumps. */
export function elementName(element: Element): string {
  const code = element.code?.trim() || "";
  const parts = code.split("+");
  const jumpNames = parts.map((part) => {
    const match = /^([1-5])(Lz|Lo|A|T|S|F)(?:[<qe!>]+)?$/.exec(part.trim());
    return match ? `${rotations[match[1]]} ${jumps[match[2]]}` : null;
  });
  if ((!element.kind || element.kind.toLowerCase() === "jump") && jumpNames.every(Boolean))
    return jumpNames.join(" + ");
  if (/^ChSq\d*$/.test(code)) return "Choreographic Sequence";
  if (/^StSq\d*$/.test(code)) return "Step Sequence";
  const name = element.name?.trim();
  if (name && name !== code) return name;
  if (element.kind?.toLowerCase() === "spin") return "Spin";
  return name || code || "Detected element";
}

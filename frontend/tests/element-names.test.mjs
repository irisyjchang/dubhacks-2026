import { test } from "node:test";
import assert from "node:assert/strict";
import { elementName } from "../src/lib/element-names.ts";

test("expands ISU jump codes into proper jump names with rotations", () => {
  const jumps = { A: "Axel", T: "Toe Loop", S: "Salchow", Lo: "Loop", F: "Flip", Lz: "Lutz" };
  const rotations = ["Single", "Double", "Triple", "Quadruple", "Quintuple"];
  rotations.forEach((rotation, index) => {
    for (const [code, name] of Object.entries(jumps)) {
      assert.equal(elementName({ code: String(index + 1) + code, kind: "jump", name: "Jump" }), rotation + " " + name);
    }
  });
  assert.equal(elementName({ code: "3Lz+3T", kind: "jump" }), "Triple Lutz + Triple Toe Loop");
  assert.equal(elementName({ code: "3A<", kind: "jump" }), "Triple Axel");
});

test("preserves spins and identifies sequences without inventing jumps", () => {
  assert.equal(elementName({ name: "Flying Camel Spin", kind: "spin", code: "FCSp4" }), "Flying Camel Spin");
  assert.equal(elementName({ name: "ChSq1", kind: "choreo", code: "ChSq1" }), "Choreographic Sequence");
  assert.equal(elementName({ code: "StSq3", kind: "step sequence" }), "Step Sequence");
  assert.equal(elementName({ name: "Detected Spin", kind: "spin", code: "3A" }), "Detected Spin");
  assert.equal(elementName({ name: "Waltz Jump", kind: "jump" }), "Waltz Jump");
});

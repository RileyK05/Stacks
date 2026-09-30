import assert from "node:assert/strict";
import test from "node:test";

const policy = { maxChars: 10000, maxSlides: 20, maxShapes: 100 };

function installPowerPoint(slides, { supported = true, failSlideShapeLists = new Set(), failTextShapes = new Set() } = {}) {
  globalThis.Office = {
    context: { requirements: { isSetSupported: (name, version) => supported && name === "PowerPointApi" && version === "1.4" } },
  };
  globalThis.PowerPoint = {
    run: async (batch) => batch({
      presentation: {
        slides: {
          items: slides,
          load() {},
          getItem(id) {
            const slide = slides.find((candidate) => candidate.id === id);
            if (!slide) throw new Error(`Unknown slide ${id}`);
            return {
              shapes: {
                items: slide.shapes,
                load() {
                  if (failSlideShapeLists.has(id)) throw new Error("shape collection offline");
                },
                getItem(shapeId) {
                  const shape = slide.shapes.find((candidate) => candidate.id === shapeId);
                  if (!shape) throw new Error(`Unknown shape ${shapeId}`);
                  return {
                    load() {
                      if (failTextShapes.has(shapeId) || shape.fail) throw new Error("text frame unavailable");
                    },
                    textFrame: {
                      hasText: Boolean(shape.text),
                      textRange: { text: shape.text ?? "" },
                    },
                  };
                },
              },
            };
          },
        },
      },
      sync: async () => {},
    }),
  };
}

async function reader() {
  return import("./public/readers/powerpoint.js");
}

test("reads every unselected slide in order with stable slide and shape labels", async () => {
  installPowerPoint([
    { id: "slide-a", shapes: [{ id: "shape-1", name: "Title", type: "Placeholder", text: "First slide" }] },
    { id: "slide-b", shapes: [{ id: "shape-2", name: "Tail", type: "TextBox", text: "Last slide, not selected" }] },
  ]);
  const { readPowerPointDocument } = await reader();
  const result = await readPowerPointDocument(policy);
  assert.match(result.text, /Slide 1 \(ID: slide-a\)/);
  assert.match(result.text, /Slide 2 \(ID: slide-b\)/);
  assert.match(result.text, /Last slide, not selected/);
  assert.match(result.text, /shape-2 \(Tail\)/);
  assert.equal(result.coverage, "partial");
});

test("skips unsupported shapes and retains readable text when a frame fails", async () => {
  installPowerPoint([{
    id: "s1",
    shapes: [
      { id: "text-before", name: "Before", type: "TextBox", text: "Readable before" },
      { id: "photo", name: "Photo", type: "Image" },
      { id: "bad", name: "Broken", type: "GeometricShape", fail: true },
      { id: "text-after", name: "After", type: "GeometricShape", text: "Readable after" },
    ],
  }]);
  const { readPowerPointDocument } = await reader();
  const result = await readPowerPointDocument(policy);
  assert.match(result.text, /Readable before/);
  assert.match(result.text, /Readable after/);
  assert.ok(result.warnings.some((warning) => warning.includes("photo") && warning.includes("omitted")));
  assert.ok(result.warnings.some((warning) => warning.includes("Broken") && warning.includes("text frame")));
});

test("rejects decks with no readable text", async () => {
  installPowerPoint([{ id: "empty", shapes: [{ id: "shape", type: "TextBox", text: "" }] }]);
  const { readPowerPointDocument } = await reader();
  await assert.rejects(readPowerPointDocument(policy), /no readable text/);
});

test("rejects whitespace-only shape text instead of treating labels as readable content", async () => {
  installPowerPoint([{ id: "whitespace", shapes: [{ id: "blank", name: "Blank", type: "TextBox", text: " \n\t " }] }]);
  const { readPowerPointDocument } = await reader();
  await assert.rejects(readPowerPointDocument(policy), /no readable text/);
});

test("aggregates many unsupported shapes into a bounded, scoped warning", async () => {
  const unsupported = Array.from({ length: 45 }, (_, index) => ({
    id: `image-${index + 1}`,
    name: `Figure ${index + 1}`,
    type: "Image",
  }));
  installPowerPoint([{ id: "s1", shapes: [
    { id: "readable", type: "TextBox", text: "Keep this text" },
    ...unsupported,
  ] }]);
  const { readPowerPointDocument } = await reader();
  const result = await readPowerPointDocument(policy);
  const omission = result.warnings.find((warning) => warning.includes("unsupported shapes"));
  assert.ok(omission);
  assert.match(omission, /45 unsupported shapes were omitted/);
  assert.match(omission, /Slide 1, shape image-1/);
  assert.ok(result.warnings.length < 30);
  assert.ok(result.warnings.some((warning) => warning.startsWith("Coverage is partial")));
});

test("reports a tiny character cap that is exhausted inside a slide label", async () => {
  installPowerPoint([{ id: "s1", shapes: [{ id: "shape", name: "Text", type: "TextBox", text: "Captured body" }] }]);
  const { readPowerPointDocument } = await reader();
  await assert.rejects(readPowerPointDocument({ ...policy, maxChars: 8 }), (error) => {
    assert.match(error.message, /no readable text/);
    assert.match(error.message, /Character limit reached at 8 characters/);
    return true;
  });
});

test("reports global slide, shape, and character limits", async () => {
  installPowerPoint([
    { id: "s1", shapes: [{ id: "a", name: "A", type: "TextBox", text: "Alpha content" }] },
    { id: "s2", shapes: [{ id: "b", name: "B", type: "TextBox", text: "Beta content" }] },
    { id: "s3", shapes: [{ id: "c", name: "C", type: "TextBox", text: "Gamma content" }] },
  ]);
  const { readPowerPointDocument } = await reader();

  const slideLimited = await readPowerPointDocument({ ...policy, maxSlides: 2 });
  assert.ok(slideLimited.warnings.some((warning) => warning.includes("Slide limit reached")));
  assert.match(slideLimited.text, /Beta content/);
  assert.doesNotMatch(slideLimited.text, /Gamma content/);

  const shapeLimited = await readPowerPointDocument({ ...policy, maxShapes: 1 });
  assert.ok(shapeLimited.warnings.some((warning) => warning.includes("Shape limit reached")));
  assert.ok(!shapeLimited.warnings.some((warning) => warning.includes("Character limit reached")));
  assert.match(shapeLimited.text, /Alpha content/);
  assert.doesNotMatch(shapeLimited.text, /Beta content/);

  const charLimited = await readPowerPointDocument({ ...policy, maxChars: 100 });
  assert.ok(charLimited.text.length <= 100);
  assert.ok(charLimited.warnings.some((warning) => warning.includes("Character limit reached")));
  assert.match(charLimited.text, /Alpha content/);
});

test("does not leave a dangling high surrogate when the character cap splits a pair", async () => {
  installPowerPoint([{ id: "s1", shapes: [{ id: "emoji", type: "TextBox", text: "A😀B" }] }]);
  const { readPowerPointDocument } = await reader();
  const full = await readPowerPointDocument(policy);
  const bodyStart = full.text.indexOf("A😀B");
  const clipped = await readPowerPointDocument({ ...policy, maxChars: bodyStart + 2 });
  const lastUnit = clipped.text.charCodeAt(clipped.text.length - 1);
  assert.ok(lastUnit < 0xd800 || lastUnit > 0xdbff);
  assert.ok(clipped.warnings.some((warning) => warning.includes("Character limit reached")));
});

test("reports failed later slides and keeps previously read text", async () => {
  installPowerPoint([
    { id: "s1", shapes: [{ id: "first", type: "TextBox", text: "Keep this text" }] },
    { id: "s2", shapes: [{ id: "never", type: "TextBox", text: "unavailable" }] },
  ], { failSlideShapeLists: new Set(["s2"]) });
  const { readPowerPointDocument } = await reader();
  const result = await readPowerPointDocument(policy);
  assert.match(result.text, /Keep this text/);
  assert.ok(result.warnings.some((warning) => warning.includes("Slide 2") && warning.includes("offline")));
});

test("throws a capability error when PowerPointApi 1.4 is unavailable", async () => {
  installPowerPoint([], { supported: false });
  const { readPowerPointDocument } = await reader();
  await assert.rejects(readPowerPointDocument(policy), (error) => error.code === "UNSUPPORTED_HOST");
});

test("requires policy limits instead of applying reader defaults", async () => {
  installPowerPoint([{ id: "s1", shapes: [{ id: "shape", type: "TextBox", text: "Text" }] }]);
  const { readPowerPointDocument } = await reader();
  await assert.rejects(readPowerPointDocument({ maxSlides: 2, maxShapes: 10 }), /maxChars policy limit/);
});

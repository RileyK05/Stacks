import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const originalOffice = globalThis.Office;
const originalWord = globalThis.Word;

afterEach(() => {
  if (originalOffice === undefined) delete globalThis.Office;
  else globalThis.Office = originalOffice;
  if (originalWord === undefined) delete globalThis.Word;
  else globalThis.Word = originalWord;
});

async function loadReader() {
  return import(`./public/readers/word.js?test=${Math.random()}`);
}

function installWord(bodyText, { supported = true, runError } = {}) {
  const calls = { loaded: [], synced: 0 };
  globalThis.Office = {
    context: {
      requirements: {
        isSetSupported(set, version) {
          assert.equal(set, "WordApi");
          assert.equal(version, "1.1");
          return supported;
        },
      },
    },
  };
  globalThis.Word = {
    async run(callback) {
      if (runError) throw runError;
      return callback({
        document: {
          body: {
            text: bodyText,
            load(property) {
              calls.loaded.push(property);
            },
          },
        },
        async sync() {
          calls.synced += 1;
        },
      });
    },
  };
  return calls;
}

test("reads the full document body, including off-screen tail and table text", async () => {
  const text = `Opening paragraph.\nTable cell A\tTable cell B\n${"tail text ".repeat(30)}`;
  const calls = installWord(text);
  const { readWordDocument } = await loadReader();

  const result = await readWordDocument({ maxChars: 1000 });

  assert.equal(result.text, text);
  assert.equal(result.coverage, "partial");
  assert.match(result.warnings.join(" "), /headers, footers, footnotes, endnotes, comments, images/);
  assert.deepEqual(calls.loaded, ["text"]);
  assert.equal(calls.synced, 1);
});

test("bounds text and reports truncation", async () => {
  installWord("0123456789\nrest");
  const { readWordDocument } = await loadReader();

  const result = await readWordDocument({ maxChars: 10 });

  assert.equal(result.text, "0123456789");
  assert.ok(result.warnings.some((warning) => warning.includes("truncated at the 10-character limit")));
});

test("does not leave a split surrogate pair at the character limit", async () => {
  installWord("abc😀tail");
  const { readWordDocument } = await loadReader();

  const result = await readWordDocument({ maxChars: 4 });

  assert.equal(result.text, "abc");
});

test("rejects a whitespace-only body", async () => {
  installWord(" \n\t ");
  const { readWordDocument } = await loadReader();

  await assert.rejects(readWordDocument({ maxChars: 100 }), /contains no readable text/);
});

test("reports unsupported Word hosts with a stable error code", async () => {
  installWord("body", { supported: false });
  const { readWordDocument } = await loadReader();

  await assert.rejects(readWordDocument({ maxChars: 100 }), (error) => {
    assert.equal(error.code, "UNSUPPORTED_HOST");
    assert.match(error.message, /does not support/);
    return true;
  });
});

test("surfaces host read failures", async () => {
  const hostError = new Error("Word sync failed");
  installWord("body", { runError: hostError });
  const { readWordDocument } = await loadReader();

  await assert.rejects(readWordDocument({ maxChars: 100 }), (error) => error === hostError);
});

test("requires an explicit valid character policy", async () => {
  installWord("body");
  const { readWordDocument } = await loadReader();

  await assert.rejects(readWordDocument(), /positive integer maxChars/);
  await assert.rejects(readWordDocument({ maxChars: 0 }), /positive integer maxChars/);
});

function validateOptions(options) {
  if (!options || !Number.isSafeInteger(options.maxChars) || options.maxChars < 1) {
    throw new TypeError("Word reader requires a positive integer maxChars policy.");
  }
}

function unsupportedHostError() {
  return Object.assign(
    new Error("This Office host does not support reading Word document bodies."),
    { code: "UNSUPPORTED_HOST" },
  );
}

function truncateAtCharacterLimit(text, maxChars) {
  if (text.length <= maxChars) return { text, truncated: false };

  let boundedText = text.slice(0, maxChars);
  const lastCodeUnit = boundedText.charCodeAt(boundedText.length - 1);
  if (lastCodeUnit >= 0xd800 && lastCodeUnit <= 0xdbff) {
    boundedText = boundedText.slice(0, -1);
  }
  return { text: boundedText, truncated: true };
}

/** Read the active Word document body through Office.js. */
export async function readWordDocument(options) {
  validateOptions(options);

  if (
    typeof Office === "undefined" ||
    !Office.context?.requirements?.isSetSupported?.("WordApi", "1.1") ||
    typeof Word === "undefined" ||
    typeof Word.run !== "function"
  ) {
    throw unsupportedHostError();
  }

  const bodyText = await Word.run(async (context) => {
    const body = context.document.body;
    body.load("text");
    await context.sync();
    return body.text;
  });

  if (typeof bodyText !== "string" || bodyText.trim().length === 0) {
    throw new Error("The Word document body contains no readable text.");
  }

  const bounded = truncateAtCharacterLimit(bodyText, options.maxChars);
  const warnings = [
    "Capture is partial: headers, footers, footnotes, endnotes, comments, images, and other non-body regions are omitted.",
  ];
  if (bounded.truncated) {
    warnings.push(`Document body was truncated at the ${options.maxChars}-character limit.`);
  }

  return {
    text: bounded.text,
    coverage: "partial",
    warnings,
  };
}

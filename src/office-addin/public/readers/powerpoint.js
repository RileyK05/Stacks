function policyLimit(options, key) {
  const value = options?.[key];
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`PowerPoint reader requires a positive integer ${key} policy limit.`);
  }
  return value;
}

function unsupportedHost(message) {
  return Object.assign(new Error(message), { code: "UNSUPPORTED_HOST" });
}

function shortError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.slice(0, 120);
}

/**
 * Reads supported text frames from every slide in the presentation.
 * @param {{maxChars: number, maxSlides: number, maxShapes: number}} options
 * @returns {Promise<{text: string, coverage: 'partial'|'document', warnings: string[]}>}
 */
export async function readPowerPointDocument(options) {
  const maxChars = policyLimit(options, "maxChars");
  const maxSlides = policyLimit(options, "maxSlides");
  const maxShapes = policyLimit(options, "maxShapes");
  const omissions = { count: 0, examples: [] };
  const textFailures = { count: 0, examples: [] };
  const slideFailures = { count: 0, examples: [] };
  const slideLimitReached = { value: false };
  const shapeLimitReached = { value: false };
  const characterLimitReached = { value: false };
  const warnings = [];

  if (typeof PowerPoint === "undefined" || typeof PowerPoint.run !== "function" ||
      typeof Office === "undefined" || !Office.context?.requirements?.isSetSupported?.("PowerPointApi", "1.4")) {
    throw unsupportedHost("This PowerPoint host does not support the PowerPointApi 1.4 text reader.");
  }

  let slideIds;
  try {
    slideIds = await PowerPoint.run(async (context) => {
      const slides = context.presentation.slides;
      slides.load("items/id");
      await context.sync();
      return slides.items.map((slide) => slide.id);
    });
  } catch (error) {
    throw new Error(`Could not enumerate presentation slides: ${shortError(error)}`);
  }

  if (slideIds.length === 0) {
    throw new Error("The presentation has no readable slides.");
  }

  let text = "";
  let shapeCount = 0;
  let readableCharacters = 0;
  const append = (value) => {
    if (value.length === 0) return { complete: true, added: "" };
    const remaining = Math.max(0, maxChars - text.length);
    let added = value.slice(0, remaining);
    const lastUnit = added.charCodeAt(added.length - 1);
    if (added.length > 0 && lastUnit >= 0xd800 && lastUnit <= 0xdbff && added.length < value.length) {
      added = added.slice(0, -1);
    }
    text += added;
    const complete = added.length === value.length;
    if (!complete) characterLimitReached.value = true;
    return { complete, added };
  };

  const slideLimit = Math.min(slideIds.length, maxSlides);
  if (slideIds.length > maxSlides) {
    slideLimitReached.value = true;
  }

  for (let slideIndex = 0; slideIndex < slideLimit && !characterLimitReached.value && !shapeLimitReached.value; slideIndex += 1) {
    const slideId = slideIds[slideIndex];
    const slideNumber = slideIndex + 1;
    if (!append(`\n--- Slide ${slideNumber} (ID: ${slideId}) ---\n`).complete) break;

    let shapeInfos;
    try {
      shapeInfos = await PowerPoint.run(async (context) => {
        const slide = context.presentation.slides.getItem(slideId);
        slide.shapes.load("items/id,name,type");
        await context.sync();
        return slide.shapes.items.map((shape) => ({ id: shape.id, name: shape.name, type: shape.type }));
      });
    } catch (error) {
      slideFailures.count += 1;
      if (slideFailures.examples.length < 2) {
        slideFailures.examples.push(`Slide ${slideNumber} (ID: ${slideId}): ${shortError(error)}`);
      }
      continue;
    }

    for (const info of shapeInfos) {
      if (shapeCount >= maxShapes) {
        shapeLimitReached.value = true;
        break;
      }
      shapeCount += 1;
      const label = `Slide ${slideNumber}, shape ${info.id}${info.name ? ` (${info.name})` : ""}`;

      if (!["TextBox", "GeometricShape", "Placeholder"].includes(info.type)) {
        omissions.count += 1;
        if (omissions.examples.length < 2) omissions.examples.push(`${label} (${info.type})`);
        continue;
      }

      try {
        const shapeText = await PowerPoint.run(async (context) => {
          const shape = context.presentation.slides.getItem(slideId).shapes.getItem(info.id);
          shape.load({ textFrame: { hasText: true, textRange: { text: true } } });
          await context.sync();
          if (!shape.textFrame.hasText) return "";
          return shape.textFrame.textRange.text;
        });
        if (shapeText.length === 0) continue;
        if (!append(`\n[${label}]\n`).complete) break;
        const capturedShapeText = append(shapeText).added;
        if (capturedShapeText.trim().length > 0) {
          readableCharacters += capturedShapeText.trim().length;
        }
        if (characterLimitReached.value) break;
        if (!append("\n").complete) break;
      } catch (error) {
        textFailures.count += 1;
        if (textFailures.examples.length < 2) textFailures.examples.push(`${label}: ${shortError(error)}`);
      }
    }
  }

  if (slideLimitReached.value) warnings.push(`Slide limit reached at ${slideLimit} of ${slideIds.length} slides.`);
  if (shapeLimitReached.value) warnings.push(`Shape limit reached at ${maxShapes} shapes; remaining presentation shapes were omitted.`);
  if (characterLimitReached.value) warnings.push(`Character limit reached at ${maxChars} characters; later content was omitted.`);
  if (omissions.count > 0) {
    warnings.push(`${omissions.count} unsupported shape${omissions.count === 1 ? " was" : "s were"} omitted (only text boxes, geometric shapes, and placeholders are read). Examples: ${omissions.examples.join("; ")}.`);
  }
  if (textFailures.count > 0) {
    warnings.push(`${textFailures.count} shape text frame${textFailures.count === 1 ? " failed" : "s failed"} to read. Examples: ${textFailures.examples.join("; ")}.`);
  }
  if (slideFailures.count > 0) {
    warnings.push(`${slideFailures.count} slide shape collection${slideFailures.count === 1 ? " failed" : "s failed"} to read. Examples: ${slideFailures.examples.join("; ")}.`);
  }
  if (readableCharacters === 0) {
    throw new Error(warnings.length
      ? `The presentation contains no readable text. ${warnings.join(" ")} Coverage is partial: speaker notes, grouped and table content, chart and SmartArt text, images, and other unsupported slide content are omitted.`
      : "The presentation contains no readable text.");
  }

  warnings.push("Coverage is partial: speaker notes, grouped and table content, chart and SmartArt text, images, and other unsupported slide content are omitted.");
  return { text, coverage: "partial", warnings };
}

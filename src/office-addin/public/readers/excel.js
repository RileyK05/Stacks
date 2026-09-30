const LIMIT_WARNING = 'The capture stopped at a configured limit.';
const MAX_WARNINGS = 30;
const MAX_DETAIL_WARNINGS = MAX_WARNINGS - 5;

/**
 * @param {unknown} options
 * @returns {{maxChars: number, maxCells: number, maxSheets: number, chunkRows: number, chunkColumns: number}}
 */
function readPolicy(options) {
  if (!options || typeof options !== 'object') throw new TypeError('Excel reader policy is required.');
  const policy = /** @type {Record<string, unknown>} */ (options);
  const names = ['maxChars', 'maxCells', 'maxSheets', 'chunkRows', 'chunkColumns'];
  for (const name of names) {
    const value = policy[name];
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
      throw new TypeError(`Excel reader policy ${name} must be a positive integer.`);
    }
  }
  return /** @type {{maxChars: number, maxCells: number, maxSheets: number, chunkRows: number, chunkColumns: number}} */ (policy);
}

function unsupportedHost() {
  const error = new Error('This Excel host does not support workbook reading with ExcelApi 1.4.');
  /** @type {Error & {code?: string}} */ (error).code = 'UNSUPPORTED_HOST';
  return error;
}

function columnName(zeroBased) {
  let number = zeroBased + 1;
  let name = '';
  while (number > 0) {
    const remainder = (number - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    number = Math.floor((number - 1) / 26);
  }
  return name;
}

function cellAddress(rowIndex, columnIndex) {
  return `${columnName(columnIndex)}${rowIndex + 1}`;
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '';
  return typeof value === 'string' ? value : String(value);
}

function cellLine(sheetName, visibility, address, value, displayed, formula) {
  const formulaText = typeof formula === 'string' && formula.startsWith('=') ? `; formula=${JSON.stringify(formula)}` : '';
  const visibilityText = visibility === 'Visible' ? '' : ` (${visibility.toLowerCase()})`;
  return `'${sheetName.replaceAll("'", "''")}'${visibilityText}!${address}: value=${JSON.stringify(value ?? null)}; text=${JSON.stringify(displayValue(displayed))}${formulaText}`;
}

/**
 * Read a bounded snapshot of an Excel workbook. All returned captures are partial
 * because Office.js does not expose every workbook feature as readable text.
 * @param {{maxChars: number, maxCells: number, maxSheets: number, chunkRows: number, chunkColumns: number}} options
 * @returns {Promise<{text: string, coverage: 'partial', warnings: string[]}>}
 */
export async function readExcelDocument(options) {
  const policy = readPolicy(options);
  if (typeof Excel === 'undefined' || typeof Office === 'undefined' ||
      typeof Office.context?.requirements?.isSetSupported !== 'function' ||
      !Office.context.requirements.isSetSupported('ExcelApi', '1.4') || typeof Excel.run !== 'function') {
    throw unsupportedHost();
  }

  const descriptors = await Excel.run(async context => {
    const worksheets = context.workbook.worksheets;
    worksheets.load('items/id,items/name,items/visibility');
    await context.sync();
    return worksheets.items.map(sheet => ({ id: sheet.id, name: sheet.name, visibility: sheet.visibility }));
  });
  if (descriptors.length === 0) throw new Error('This workbook has no readable worksheets.');

  const selected = descriptors.slice(0, policy.maxSheets);
  const detailWarnings = new Map();
  let suppressedWarnings = 0;
  const readFailure = (stage, name, error, cellsBefore) => {
    const reason = error instanceof Error ? error.message : String(error);
    const key = `${stage}:${reason}`;
    const entry = detailWarnings.get(key);
    if (entry) {
      entry.count += 1;
      entry.names.add(name);
      return;
    }
    if (detailWarnings.size >= MAX_DETAIL_WARNINGS) {
      suppressedWarnings += 1;
      return;
    }
    detailWarnings.set(key, {
      message: `Could not read ${stage} for worksheet '${name}' after ${cellsBefore} requested cells: ${reason}`,
      count: 1,
      names: new Set([name]),
      stage,
      cellsBefore,
      reason
    });
  };

  /** @type {string[]} */
  const lines = [];
  let chars = 0;
  let cellsRequested = 0;
  let anyReadableCell = false;
  let charLimitReached = false;
  let cellLimitReached = false;
  const append = line => {
    const separatorLength = lines.length ? 1 : 0;
    if (chars + separatorLength + line.length > policy.maxChars) {
      charLimitReached = true;
      return false;
    }
    lines.push(line);
    chars += separatorLength + line.length;
    return true;
  };

  for (let sheetIndex = 0; sheetIndex < selected.length; sheetIndex += 1) {
    const descriptor = selected[sheetIndex];
    if (cellsRequested >= policy.maxCells) {
      cellLimitReached = true;
      break;
    }
    const { id, name, visibility } = descriptor;
    /** @type {{isNullObject: boolean, rowIndex: number, columnIndex: number, rowCount: number, columnCount: number} | null} */
    let bounds = null;
    try {
      bounds = await Excel.run(async context => {
        const sheet = context.workbook.worksheets.getItem(id);
        const used = sheet.getUsedRangeOrNullObject(true);
        used.load('isNullObject,rowIndex,columnIndex,rowCount,columnCount');
        await context.sync();
        return {
          isNullObject: used.isNullObject,
          rowIndex: used.rowIndex,
          columnIndex: used.columnIndex,
          rowCount: used.rowCount,
          columnCount: used.columnCount
        };
      });
    } catch (error) {
      readFailure('used range', name, error, cellsRequested);
      continue;
    }

    if (bounds.isNullObject) {
      if (!append(`Sheet '${name}'${visibility === 'Visible' ? '' : ` (${visibility.toLowerCase()})`}: empty sheet.`)) break;
      continue;
    }
    const totalRows = bounds.rowCount;
    const totalColumns = bounds.columnCount;
    let sheetHadContent = false;
    let sheetFailed = false;
    let rowOffset = 0;

    while (rowOffset < totalRows && !charLimitReached && !sheetFailed) {
      const targetRows = Math.min(policy.chunkRows, totalRows - rowOffset);
      let rowsCovered = targetRows;
      let columnOffset = 0;
      while (columnOffset < totalColumns && !charLimitReached && !sheetFailed) {
        const remaining = policy.maxCells - cellsRequested;
        if (remaining <= 0) {
          cellLimitReached = true;
          sheetFailed = true;
          break;
        }
        const desiredColumns = Math.min(policy.chunkColumns, totalColumns - columnOffset);
        const columns = Math.min(desiredColumns, remaining);
        const boundedRows = Math.min(targetRows, Math.floor(remaining / columns));
        if (boundedRows <= 0 || columns <= 0) {
          cellLimitReached = true;
          sheetFailed = true;
          break;
        }
        const requested = boundedRows * columns;
        const startRow = bounds.rowIndex + rowOffset;
        const startColumn = bounds.columnIndex + columnOffset;
        const address = `${cellAddress(startRow, startColumn)}:${cellAddress(startRow + boundedRows - 1, startColumn + columns - 1)}`;
        cellsRequested += requested;
        let data;
        try {
          data = await Excel.run(async context => {
            const sheet = context.workbook.worksheets.getItem(id);
            const range = sheet.getRange(address);
            range.load('values,text,formulas');
            await context.sync();
            return { values: range.values, text: range.text, formulas: range.formulas };
          });
        } catch (error) {
          readFailure('cell range', name, error, cellsRequested - requested);
          sheetFailed = true;
          break;
        }

        for (let row = 0; row < boundedRows && !charLimitReached; row += 1) {
          for (let column = 0; column < columns; column += 1) {
            const value = data.values[row]?.[column];
            const displayed = data.text[row]?.[column];
            const formula = data.formulas[row]?.[column];
            const hasFormula = typeof formula === 'string' && formula.startsWith('=');
            const hasValue = value !== null && value !== undefined && value !== '';
            const hasText = displayValue(displayed) !== '';
            if (!hasFormula && !hasValue && !hasText) continue;
            const absoluteRow = startRow + row;
            const absoluteColumn = startColumn + column;
            const line = cellLine(name, visibility, cellAddress(absoluteRow, absoluteColumn), value, displayed, formula);
            if (!append(line)) break;
            sheetHadContent = true;
            anyReadableCell = true;
          }
        }
        rowsCovered = Math.min(rowsCovered, boundedRows);
        columnOffset += columns;
        if (cellsRequested >= policy.maxCells && (rowOffset + rowsCovered < totalRows || columnOffset < totalColumns)) {
          cellLimitReached = true;
          sheetFailed = true;
        }
      }
      rowOffset += rowsCovered;
    }

    if (!sheetFailed && !charLimitReached && !sheetHadContent) {
      append(`Sheet '${name}'${visibility === 'Visible' ? '' : ` (${visibility.toLowerCase()})`}: no readable cell values.`);
    }
    if (charLimitReached) break;
    if (cellLimitReached) break;
  }

  const limitWarnings = [];
  if (descriptors.length > selected.length) {
    limitWarnings.push(`Only the first ${selected.length} of ${descriptors.length} worksheets were read because maxSheets was reached.`);
  }
  if (cellLimitReached) limitWarnings.push(`${LIMIT_WARNING} maxCells=${policy.maxCells} rectangular cell reads.`);
  if (charLimitReached) limitWarnings.push(`${LIMIT_WARNING} maxChars=${policy.maxChars}.`);
  const warnings = ['Workbook capture is partial: charts, images, pivot semantics, formatting, and other non-cell content may be omitted.'];
  for (const entry of detailWarnings.values()) {
    if (entry.names) {
      const names = [...entry.names];
      const shownNames = names.slice(0, 3).map(name => `'${name}'`).join(', ');
      const otherCount = names.length - Math.min(3, names.length);
      const affected = `${shownNames}${otherCount > 0 ? ` and ${otherCount} other worksheet(s)` : ''}`;
      warnings.push(`Could not read ${entry.stage} for ${affected} after ${entry.cellsBefore} requested cells: ${entry.reason}${entry.count > 1 ? ` (${entry.count} failures)` : ''}`);
    } else {
      warnings.push(`${entry.message}${entry.count > 1 ? ` (${entry.count} occurrences)` : ''}`);
    }
  }
  if (suppressedWarnings > 0) warnings.push(`${suppressedWarnings} additional read warning(s) were omitted to keep the warning list bounded.`);
  warnings.push(...limitWarnings);
  if (!anyReadableCell) throw new Error('This workbook contains no readable cell values within the configured limits.');
  return { text: lines.join('\n'), coverage: 'partial', warnings };
}

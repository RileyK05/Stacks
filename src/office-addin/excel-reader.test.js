import test from 'node:test';
import assert from 'node:assert/strict';
import { readExcelDocument } from './public/readers/excel.js';

const policy = overrides => ({
  maxChars: 10000,
  maxCells: 1000,
  maxSheets: 20,
  chunkRows: 20,
  chunkColumns: 20,
  ...overrides
});

function colIndex(name) {
  let value = 0;
  for (const character of name) value = value * 26 + character.charCodeAt(0) - 64;
  return value - 1;
}

function addressParts(address) {
  const [start, end = start] = address.split(':');
  const parse = cell => {
    const match = /^([A-Z]+)(\d+)$/.exec(cell);
    assert.ok(match, `expected an A1 address, got ${cell}`);
    return { row: Number(match[2]) - 1, column: colIndex(match[1]) };
  };
  return [parse(start), parse(end)];
}

function installWorkbook(definitions) {
  const requests = [];
  const worksheets = definitions.map((definition, index) => {
    const sheet = {
      id: `sheet-${index + 1}`,
      name: definition.name,
      visibility: definition.visibility || 'Visible',
      getUsedRangeOrNullObject(valuesOnly) {
        assert.equal(valuesOnly, true);
        return {
          ...definition.bounds,
          isNullObject: definition.bounds == null,
          load(properties) { assert.equal(properties, 'isNullObject,rowIndex,columnIndex,rowCount,columnCount'); }
        };
      },
      getRange(address) {
        requests.push({ sheet: definition.name, address });
        const [start, end] = addressParts(address);
        const rowCount = end.row - start.row + 1;
        const columnCount = end.column - start.column + 1;
        const matrix = key => Array.from({ length: rowCount }, (_, row) =>
          Array.from({ length: columnCount }, (_, column) => {
            const absRow = start.row + row;
            const absColumn = start.column + column;
            const relativeRow = absRow - (definition.bounds?.rowIndex || 0);
            const relativeColumn = absColumn - (definition.bounds?.columnIndex || 0);
            return definition[key]?.[relativeRow]?.[relativeColumn] ?? null;
          }));
        const range = { values: matrix('values'), text: matrix('text'), formulas: matrix('formulas'), load() {} };
        return range;
      }
    };
    return sheet;
  });
  globalThis.Office = { context: { requirements: { isSetSupported: (name, version) => name === 'ExcelApi' && version === '1.4' } } };
  globalThis.Excel = {
    run: callback => {
      let pending = null;
      const sheetById = new Map(worksheets.map((sheet, index) => [sheet.id, { sheet, definition: definitions[index] }]));
      const worksheetApi = {
        items: worksheets,
        load(properties) { assert.equal(properties, 'items/id,items/name,items/visibility'); },
        getItem(id) {
          const record = sheetById.get(id);
          assert.ok(record, `unknown worksheet id ${id}`);
          const { sheet, definition } = record;
          return {
            ...sheet,
            getUsedRangeOrNullObject(valuesOnly) {
              pending = { kind: 'bounds', definition };
              return sheet.getUsedRangeOrNullObject(valuesOnly);
            },
            getRange(address) {
              pending = { kind: 'range', definition, address };
              return sheet.getRange(address);
            }
          };
        }
      };
      return callback({
        workbook: { worksheets: worksheetApi },
        sync: async () => {
          const operation = pending;
          pending = null;
          if (operation?.kind === 'bounds' && operation.definition.failBounds) {
            throw new Error(typeof operation.definition.failBounds === 'string' ? operation.definition.failBounds : 'mock bounds failure');
          }
          if (operation?.kind === 'range' && operation.definition.failAddress === operation.address) throw new Error('mock range failure');
        }
      });
    }
  };
  return requests;
}

test('reads all worksheets including hidden sheets, absolute tail cells, formulas and falsy values', async () => {
  installWorkbook([
    {
      name: "O'Brien",
      visibility: 'Hidden',
      bounds: { rowIndex: 0, columnIndex: 0, rowCount: 2, columnCount: 2 },
      values: [[0, false], [null, '']],
      text: [['0', 'FALSE'], ['', '']],
      formulas: [[null, null], [null, '=IF(A1=0,"",A1)']]
    },
    {
      name: 'Tail',
      visibility: 'VeryHidden',
      bounds: { rowIndex: 49, columnIndex: 26, rowCount: 1, columnCount: 1 },
      values: [[42]], text: [['$42.00']], formulas: [[null]]
    }
  ]);
  const result = await readExcelDocument(policy({ chunkRows: 1, chunkColumns: 1 }));
  assert.equal(result.coverage, 'partial');
  assert.match(result.text, /'O''Brien' \(hidden\)!A1: value=0; text="0"/);
  assert.match(result.text, /'O''Brien' \(hidden\)!B1: value=false; text="FALSE"/);
  assert.match(result.text, /'O''Brien' \(hidden\)!B2: value=""; text=""; formula="=IF\(A1=0,/);
  assert.match(result.text, /'Tail' \(veryhidden\)!AA50: value=42; text="\$42\.00"/);
  assert.equal(result.warnings.length, 1);
});

test('uses values-only bounds and divides requests by configured rectangular chunk sizes', async () => {
  const requests = installWorkbook([{
    name: 'Grid', bounds: { rowIndex: 3, columnIndex: 2, rowCount: 5, columnCount: 4 },
    values: Array.from({ length: 8 }, (_, row) => { const cells = []; cells[0] = row + 1; return cells; })
  }]);
  const result = await readExcelDocument(policy({ chunkRows: 2, chunkColumns: 3 }));
  assert.equal(requests.length, 6);
  for (const request of requests) {
    const [start, end] = addressParts(request.address);
    assert.ok(end.row - start.row + 1 <= 2);
    assert.ok(end.column - start.column + 1 <= 3);
  }
  assert.match(result.text, /C4/);
});

test('budgets requested cells by rectangle area and reports a partial limit', async () => {
  const requests = installWorkbook([{
    name: 'Large', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 100, columnCount: 10 },
    values: [[1]]
  }]);
  const result = await readExcelDocument(policy({ maxCells: 7, chunkRows: 3, chunkColumns: 4 }));
  const requestedCells = requests.reduce((sum, request) => {
    const [start, end] = addressParts(request.address);
    return sum + (end.row - start.row + 1) * (end.column - start.column + 1);
  }, 0);
  assert.equal(requestedCells, 7);
  assert.match(result.warnings.join(' '), /maxCells=7/);
});

test('honors sheet and character limits with warnings', async () => {
  installWorkbook([
    { name: 'First', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[1]], text: [['1']] },
    { name: 'Second', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[2]], text: [['2']] }
  ]);
  const sheetLimited = await readExcelDocument(policy({ maxSheets: 1 }));
  assert.match(sheetLimited.warnings.join(' '), /maxSheets/);
  const charLimited = await readExcelDocument(policy({ maxChars: 45 }));
  assert.match(charLimited.warnings.join(' '), /maxChars=45/);
});

test('labels empty sheets and rejects a workbook with no readable cell values', async () => {
  installWorkbook([
    { name: 'Blank', bounds: null },
    { name: 'Data', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[7]], text: [['7']] }
  ]);
  const result = await readExcelDocument(policy());
  assert.match(result.text, /Sheet 'Blank': empty sheet/);

  installWorkbook([{ name: 'Blank', bounds: null }]);
  await assert.rejects(readExcelDocument(policy()), /no readable cell values/i);
});

test('keeps earlier sheet contents if a later sheet read fails and rejects if all reads fail', async () => {
  installWorkbook([
    { name: 'Good', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [['ok']], text: [['ok']] },
    { name: 'Broken', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, failAddress: 'A1:A1' },
    { name: 'After', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [['after']], text: [['after']] }
  ]);
  const result = await readExcelDocument(policy());
  assert.match(result.text, /'Good'!A1/);
  assert.match(result.text, /'After'!A1/);
  assert.match(result.warnings.join(' '), /Broken/);

  installWorkbook([{ name: 'Broken', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, failAddress: 'A1:A1' }]);
  await assert.rejects(readExcelDocument(policy()), /no readable cell values/i);
});

test('a failed later used-range sync preserves earlier cells and allows a following worksheet', async () => {
  installWorkbook([
    { name: 'Before', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [['before']], text: [['before']] },
    { name: 'Protected', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, failBounds: true },
    { name: 'After', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [['after']], text: [['after']] }
  ]);
  const result = await readExcelDocument(policy());
  assert.match(result.text, /'Before'!A1/);
  assert.match(result.text, /'After'!A1/);
  assert.match(result.warnings.join(' '), /used range.*Protected.*mock bounds failure/);
});

test('exactly reaching maxCells warns when later worksheets were left unread', async () => {
  installWorkbook([
    { name: 'First', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[1]], text: [['1']] },
    { name: 'Unread', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[2]], text: [['2']] }
  ]);
  const result = await readExcelDocument(policy({ maxCells: 1 }));
  assert.match(result.text, /'First'!A1/);
  assert.doesNotMatch(result.text, /Unread/);
  assert.match(result.warnings.join(' '), /maxCells=1/);
});

test('bounds warning aggregation stays within 30 and keeps the maxSheets notice', async () => {
  const definitions = [
    { name: 'Readable', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[1]], text: [['1']] },
    ...Array.from({ length: 31 }, (_, index) => ({ name: `Bad ${index}`, bounds: null, failBounds: `failure ${index}` })),
    { name: 'Tail', bounds: { rowIndex: 0, columnIndex: 0, rowCount: 1, columnCount: 1 }, values: [[2]], text: [['2']] },
    { name: 'Overflow', bounds: null }
  ];
  installWorkbook(definitions);
  const result = await readExcelDocument(policy({ maxSheets: 33 }));
  assert.ok(result.warnings.length <= 30);
  assert.match(result.warnings.join(' '), /maxSheets/);
  assert.match(result.warnings.join(' '), /additional read warning/);
  assert.match(result.text, /'Tail'!A1/);
});

test('fails clearly when ExcelApi 1.4 is unavailable and requires every policy limit', async () => {
  installWorkbook([]);
  globalThis.Office.context.requirements.isSetSupported = () => false;
  await assert.rejects(readExcelDocument(policy()), error => error.code === 'UNSUPPORTED_HOST');
  await assert.rejects(readExcelDocument({ maxCells: 1 }), /policy maxChars/);
});

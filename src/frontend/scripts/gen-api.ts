import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

// The spec comes from the running backend by default; OPENAPI_FILE points
// at a dumped spec instead (`python -m scripts.dump_openapi`), so types
// can be regenerated without starting the server.
const here = dirname(fileURLToPath(import.meta.url));
const source = process.env.OPENAPI_FILE
  ? pathToFileURL(resolve(process.env.OPENAPI_FILE))
  : new URL(process.env.OPENAPI_URL ?? 'http://localhost:8000/api/openapi.json');
const outPath = resolve(here, '../src/lib/api/schema.d.ts');

const ast = await openapiTS(source, { exportType: true });
const output = astToString(ast);
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, output);
console.log(`wrote ${outPath} from ${source}`);

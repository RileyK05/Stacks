import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const here = dirname(fileURLToPath(import.meta.url));
const specUrl = process.env.OPENAPI_URL ?? 'http://localhost:8000/openapi.json';
const outPath = resolve(here, '../src/lib/api/schema.d.ts');

const ast = await openapiTS(new URL(specUrl), { exportType: true });
const output = astToString(ast);
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, output);
console.log(`wrote ${outPath} from ${specUrl}`);

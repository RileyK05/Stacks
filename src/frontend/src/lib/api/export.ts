import { invoke, isTauri } from '@tauri-apps/api/core';
import { api } from './client';

export interface ExportOrigin {
  courseId: string;
  messageId: string;
  itemIndex: number;
}

export interface ExportFile {
  filename: string;
  blob: Blob;
}

export interface SavedExport {
  path: string;
  filename: string;
}

function decodeHeaderFilename(value: string): string | null {
  const extended = value.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1]?.trim();
  if (extended) {
    try {
      return decodeURIComponent(extended.replace(/^"|"$/g, ''));
    } catch {
      // Try the ordinary filename parameter when the encoded form is malformed.
    }
  }
  const ordinary = value.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
  return ordinary?.[1]?.trim() ?? ordinary?.[2]?.trim() ?? null;
}

export function exportFilename(header: string | null, fallback: string): string {
  return (header ? decodeHeaderFilename(header) : null) || fallback;
}

async function responseFile(response: Response, blob: Blob, fallback: string): Promise<ExportFile> {
  if (!blob.size) throw new Error('The export was empty.');
  return { filename: exportFilename(response.headers.get('content-disposition'), fallback), blob };
}

export async function requestArtifactExport(
  courseId: string,
  artifactId: string,
  format: string
): Promise<ExportFile> {
  const result = await api.POST('/courses/{course_id}/artifacts/{artifact_id}/download', {
    params: { path: { course_id: courseId, artifact_id: artifactId } },
    body: { format, path: null },
    parseAs: 'blob'
  });
  if (result.error || !result.data) throw result.error ?? new Error('Could not export this artifact.');
  const blob = result.data as Blob;
  return responseFile(result.response, blob, `artifact.${format}`);
}

export async function requestWorkspaceExport(
  origin: ExportOrigin,
  format: string,
  draft: string | string[][]
): Promise<ExportFile> {
  const result = await api.POST('/courses/{course_id}/artifacts/export-from-message', {
    params: { path: { course_id: origin.courseId } },
    body: {
      format,
      message_id: origin.messageId,
      item_index: origin.itemIndex,
      as_copy: false,
      draft
    },
    parseAs: 'blob'
  });
  if (result.error || !result.data) throw result.error ?? new Error('Could not export this material.');
  const blob = result.data as Blob;
  return responseFile(result.response, blob, `material.${format}`);
}

export type NativeSave = (filename: string, data: number[]) => Promise<SavedExport | null>;
export type BrowserDownload = (file: ExportFile) => void;

async function saveNatively(filename: string, data: number[]): Promise<SavedExport | null> {
  return invoke<SavedExport | null>('save_export', { filename, data });
}

function downloadInBrowser(file: ExportFile): void {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Save an export to a chosen native destination, or trigger a browser download. */
export async function deliverExport(
  file: ExportFile,
  options: { native?: boolean; saveNative?: NativeSave; browserDownload?: BrowserDownload } = {}
): Promise<SavedExport | null> {
  const native = options.native ?? isTauri();
  if (!native) {
    (options.browserDownload ?? downloadInBrowser)(file);
    return { path: file.filename, filename: file.filename };
  }
  const bytes = [...new Uint8Array(await file.blob.arrayBuffer())];
  return (options.saveNative ?? saveNatively)(file.filename, bytes);
}

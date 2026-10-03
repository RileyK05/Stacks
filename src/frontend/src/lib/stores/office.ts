import { api } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import type { IconName } from '$lib/components/Icon.svelte';

export type OfficeStatus = components['schemas']['OfficeStatusView'];
export type OfficeApp = OfficeStatus['apps'][number];
type OpenRequest = components['schemas']['OpenInOfficeRequest'];

export const OFFICE_APPS: { id: OfficeApp; name: string; newLabel: string; icon: IconName }[] = [
  { id: 'word', name: 'Word', newLabel: 'New Word document', icon: 'file-text' },
  { id: 'excel', name: 'Excel', newLabel: 'New Excel workbook', icon: 'table' },
  { id: 'powerpoint', name: 'PowerPoint', newLabel: 'New PowerPoint deck', icon: 'presentation' }
];

export const OFFICE_EXTENSIONS = ['docx', 'docm', 'doc', 'dotx', 'rtf', 'xlsx', 'xlsm', 'xls', 'csv', 'pptx', 'pptm', 'ppt', 'potx'];

export function appName(app: OfficeApp): string {
  return OFFICE_APPS.find((entry) => entry.id === app)?.name ?? 'Office';
}

export async function officeStatus(): Promise<OfficeStatus> {
  const { data } = await api.GET('/office/status');
  if (!data) throw new Error('Office status returned an empty response.');
  return data;
}

export async function connectOffice(): Promise<OfficeStatus> {
  const { data } = await api.POST('/office/connect');
  if (!data) throw new Error('Office connection returned an empty response.');
  return data;
}

export async function disconnectOffice(): Promise<OfficeStatus> {
  const { data } = await api.POST('/office/disconnect');
  if (!data) throw new Error('Office disconnect returned an empty response.');
  return data;
}

/** Open Word, Excel or PowerPoint (connecting Office first if needed) and
 * return the message to show: where to find the Stacks button. */
export async function openInOffice(request: OpenRequest): Promise<string> {
  const { data } = await api.POST('/office/open', { body: request });
  if (!data) throw new Error('Opening Office returned an empty response.');
  const name = appName(data.app);
  return data.first_time
    ? `Opening ${name}. Find Stacks on the Home tab or under Home → Add-ins. Restart ${name} once if it was already open.`
    : `Opening ${name}. Find Stacks on the Home tab or under Home → Add-ins to open the pane.`;
}

export interface ArtifactDraft {
  key: string;
  courseId: string;
  artifactId: string;
  title: string;
  content: Record<string, unknown>;
  baseVersion: number;
  kind: string;
  origin: Record<string, unknown>;
  sources: string[];
  pendingSave?: DraftSaveIntent | null;
  revision: number;
  writerId: string;
  messageId?: string;
  itemIndex?: number;
  updatedAt: number;
}

export interface DraftSaveIntent {
  author: 'you' | 'model';
  note: string;
  sources?: string[];
}

export interface DraftStorage {
  get(key: string): Promise<ArtifactDraft | null>;
  list(keyPrefix: string): Promise<ArtifactDraft[]>;
  put(draft: ArtifactDraft): Promise<void>;
  delete(key: string, revision?: number, writerId?: string): Promise<void>;
  deleteArtifact?(courseId: string, artifactId: string): Promise<void>;
  deleteCourse?(courseId: string): Promise<void>;
  deleteMessage?(courseId: string, messageId: string): Promise<void>;
}

export async function flushDirtyEdits(
  isDirty: () => boolean,
  hasConflict: () => boolean,
  save: () => Promise<boolean>
): Promise<boolean> {
  while (isDirty()) {
    if (hasConflict() || !(await save())) return false;
  }
  return !hasConflict();
}

export async function coalesceSave(
  getInFlight: () => Promise<boolean> | null,
  setInFlight: (operation: Promise<boolean> | null) => void,
  run: () => Promise<boolean>
): Promise<boolean> {
  const ongoing = getInFlight();
  if (ongoing) return ongoing;
  const operation = run();
  setInFlight(operation);
  try {
    return await operation;
  } finally {
    if (getInFlight() === operation) setInFlight(null);
  }
}

export function matchesDraftRevision(
  draft: Pick<ArtifactDraft, 'revision' | 'writerId'> | undefined,
  revision: number,
  writerId?: string
): boolean {
  return draft?.revision === revision && (writerId === undefined || draft.writerId === writerId);
}

export function saveIntentForRetry(
  pending: DraftSaveIntent | null,
  requested: Partial<DraftSaveIntent> = {}
): DraftSaveIntent | null {
  if (Object.keys(requested).length === 0) {
    return pending
      ? { author: pending.author, note: pending.note, ...(pending.sources ? { sources: [...pending.sources] } : {}) }
      : null;
  }
  return {
    author: requested.author ?? 'you',
    note: requested.note ?? '',
    ...(requested.sources === undefined ? {} : { sources: [...requested.sources] })
  };
}

export function saveIntentAfterSuccessfulSave(
  sent: DraftSaveIntent | null,
  editsRemain: boolean
): DraftSaveIntent | null {
  if (!editsRemain || !sent?.sources) return null;
  return { author: 'you', note: '', sources: [...sent.sources] };
}

const DB_NAME = 'stacks-artifact-recovery';
const STORE_NAME = 'drafts';

function request<T>(value: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    value.onsuccess = () => resolve(value.result);
    value.onerror = () => reject(value.error ?? new Error('Could not access local recovery storage.'));
  });
}

function database(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') return Promise.reject(new Error('Local recovery storage is unavailable.'));
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open(DB_NAME, 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore(STORE_NAME, { keyPath: 'key' });
    opening.onsuccess = () => resolve(opening.result);
    opening.onerror = () => reject(opening.error ?? new Error('Could not open local recovery storage.'));
  });
}

async function transact<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  try {
    const tx = db.transaction(STORE_NAME, mode);
    const completed = new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('Local recovery storage transaction failed.'));
      tx.onabort = () => reject(tx.error ?? new Error('Local recovery storage transaction was cancelled.'));
    });
    const [result] = await Promise.all([request(run(tx.objectStore(STORE_NAME))), completed]);
    return result;
  } finally {
    db.close();
  }
}

export const artifactDraftStorage: DraftStorage = {
  async get(key) {
    return (await transact('readonly', (store) => store.get(key))) ?? null;
  },
  async list(keyPrefix) {
    return (await transact('readonly', (store) => store.getAll())).filter(
      (draft) => draft.key.startsWith(keyPrefix)
    );
  },
  async put(draft) {
    await transact('readwrite', (store) => store.put(draft));
  },
  async delete(key, revision, writerId) {
    if (revision === undefined) {
      await transact('readwrite', (store) => store.delete(key));
      return;
    }
    const db = await database();
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const get = store.get(key);
        get.onsuccess = () => {
          if (matchesDraftRevision(get.result, revision, writerId)) store.delete(key);
        };
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error ?? new Error('Could not clear local recovery data.'));
        tx.onabort = () => reject(tx.error ?? new Error('Could not clear local recovery data.'));
      });
    } finally {
      db.close();
    }
  },
  async deleteCourse(courseId) {
    await deleteMatching((draft) => draft.courseId === courseId);
  },
  async deleteArtifact(courseId, artifactId) {
    await deleteMatching((draft) => draft.courseId === courseId && draft.artifactId === artifactId);
  },
  async deleteMessage(courseId, messageId) {
    await deleteMatching((draft) => draft.courseId === courseId && draft.messageId === messageId);
  }
};

async function deleteMatching(matches: (draft: ArtifactDraft) => boolean): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const cursorRequest = tx.objectStore(STORE_NAME).openCursor();
      cursorRequest.onsuccess = () => {
        const cursor = cursorRequest.result;
        if (!cursor) return;
        if (matches(cursor.value as ArtifactDraft)) cursor.delete();
        cursor.continue();
      };
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('Could not clear local recovery data.'));
      tx.onabort = () => reject(tx.error ?? new Error('Could not clear local recovery data.'));
    });
  } finally {
    db.close();
  }
}

export function artifactDraftKey(courseId: string, artifactId: string): string {
  return `${courseId}:${artifactId}`;
}

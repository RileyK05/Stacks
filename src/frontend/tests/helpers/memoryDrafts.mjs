export class MemoryDrafts {
  records = new Map();
  puts = 0;
  failPuts = 0;
  readGate = null;

  async get(key) {
    if (this.readGate) await this.readGate;
    return this.records.get(key) ?? null;
  }

  async list(prefix) {
    if (this.readGate) await this.readGate;
    return [...this.records.values()].filter((record) => record.key.startsWith(prefix));
  }

  async put(record) {
    this.puts += 1;
    if (this.failPuts > 0) {
      this.failPuts -= 1;
      throw new Error('simulated local persistence failure');
    }
    this.records.set(record.key, structuredClone(record));
  }

  async delete(key, revision, writerId) {
    const saved = this.records.get(key);
    if (saved && (revision === undefined || (saved.revision === revision
      && (writerId === undefined || saved.writerId === writerId)))) {
      this.records.delete(key);
    }
  }

  async deleteArtifact(courseId, artifactId) {
    for (const [key, record] of this.records) {
      if (record.courseId === courseId && record.artifactId === artifactId) {
        this.records.delete(key);
      }
    }
  }
}

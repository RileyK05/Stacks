/** Commands poll for presence; only an explicit refresh reads the document. */
export class LivePane {
  constructor({ identity, read, poll, complete, onSnapshot, onLost }) {
    this.identity = identity;
    this.read = read;
    this.poll = poll;
    this.complete = complete;
    this.onSnapshot = onSnapshot;
    this.onLost = onLost;
    this.binding = null;
    this.generation = 0;
    this.inFlight = false;
  }

  bind(binding) {
    this.generation++;
    this.binding = binding;
  }

  stop() {
    const binding = this.binding;
    this.generation++;
    this.binding = null;
    return binding;
  }

  async tick() {
    if (!this.binding || this.inFlight) return;
    const binding = this.binding;
    const generation = this.generation;
    const current = () => generation === this.generation && this.binding === binding;
    this.inFlight = true;
    try {
      if (this.identity() !== binding.external_id) throw new Error('The Office document changed. Connect it again.');
      const response = await this.poll(binding.connection_id, binding.external_id);
      if (!current() || !response.command) return;
      let document = null;
      let error = '';
      try {
        document = await this.read(response.policy.reader);
      } catch (caught) {
        error = String(caught?.message || caught).slice(0, 2000);
      }
      if (!current()) return;
      if (this.identity() !== binding.external_id) throw new Error('The Office document changed while reading. Connect it again.');
      const result = await this.complete(binding.connection_id, {
        request_id: response.command.request_id,
        external_id: binding.external_id,
        document,
        error
      });
      if (current() && result.status === 'complete') this.onSnapshot(result, binding);
      if (current() && result.status === 'failed') this.onLost(new Error(result.error), false);
    } catch (error) {
      if (current()) {
        this.stop();
        this.onLost(error, true);
      }
    } finally {
      this.inFlight = false;
    }
  }
}

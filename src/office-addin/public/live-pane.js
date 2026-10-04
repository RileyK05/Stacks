/** Commands poll for presence; only an explicit refresh reads the document. */
export class LivePane {
  constructor({ identity, read, poll, complete, disconnect = async (_connectionId) => {}, onSnapshot, onLost }) {
    this.identity = identity;
    this.read = read;
    this.poll = poll;
    this.complete = complete;
    this.disconnect = disconnect;
    this.onSnapshot = onSnapshot;
    this.onLost = onLost;
    this.binding = null;
    this.generation = 0;
    this.inFlight = false;
    this.disconnecting = new WeakMap();
    this.disconnected = new WeakSet();
  }

  bind(binding) {
    const previous = this.binding;
    this.generation++;
    this.binding = binding;
    if (previous && previous.connection_id !== binding.connection_id) this.disconnectOnce(previous);
  }

  stop() {
    const binding = this.binding;
    this.generation++;
    this.binding = null;
    if (binding) this.disconnectOnce(binding);
    return binding;
  }

  disconnectOnce(binding) {
    const id = binding.connection_id;
    if (this.disconnected.has(binding) || this.disconnecting.has(binding)) return;
    const marker = {};
    this.disconnecting.set(binding, marker);
    void Promise.resolve().then(() => {
      // A fast rebind may have adopted the same server connection while its
      // former local owner was closing. In that case it is still live.
      if (this.binding?.connection_id === id) return;
      this.disconnected.add(binding);
      return this.disconnect(id);
    }).catch(() => {}).finally(() => {
      if (this.disconnecting.get(binding) === marker) this.disconnecting.delete(binding);
    });
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

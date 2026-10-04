export function createBusyOwner(setBusy: (busy: boolean) => void) {
  let sequence = 0;
  let active: number | null = null;

  return {
    claim(): number {
      const owner = ++sequence;
      active = owner;
      setBusy(true);
      return owner;
    },
    release(owner: number): void {
      if (active !== owner) return;
      active = null;
      setBusy(false);
    },
    reset(): void {
      active = null;
      setBusy(false);
    }
  };
}

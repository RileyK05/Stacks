interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
}

let prompt = $state<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    prompt = { ...options, resolve };
  });
}

export function settle(ok: boolean): void {
  prompt?.resolve(ok);
  prompt = null;
}

export function activePrompt() {
  return prompt;
}

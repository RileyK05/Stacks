export class QuizSessionScope<T> {
  private identity: string;
  private session: T;

  constructor(identity: string, create: () => T) {
    this.identity = identity;
    this.session = create();
  }

  forMode(mode: 'take' | 'edit', identity: string, create: () => T): T {
    if (mode === 'take' && identity !== this.identity) {
      this.identity = identity;
      this.session = create();
    }
    return this.session;
  }
}

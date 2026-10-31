export interface Command {
  label: string;
  undo(): void;
  redo(): void;
}

/** Undo/Redo 用のコマンドスタック */
export class History {
  private stack: Command[] = [];
  private index = -1;

  /** スタックの状態が変わったとき(ボタンの活性化更新などに使う) */
  onChange: (() => void) | null = null;

  /** コマンドを積む。execute=true なら redo() を即実行する */
  push(command: Command, execute = true): void {
    if (execute) command.redo();
    this.stack.length = this.index + 1;
    this.stack.push(command);
    this.index += 1;
    this.onChange?.();
  }

  undo(): void {
    if (!this.canUndo) return;
    this.stack[this.index].undo();
    this.index -= 1;
    this.onChange?.();
  }

  redo(): void {
    if (!this.canRedo) return;
    this.index += 1;
    this.stack[this.index].redo();
    this.onChange?.();
  }

  get canUndo(): boolean {
    return this.index >= 0;
  }

  get canRedo(): boolean {
    return this.index < this.stack.length - 1;
  }

  clear(): void {
    this.stack = [];
    this.index = -1;
    this.onChange?.();
  }
}

import type { Driver, HistoryItem, ModelTurn } from "#/features/evidence/agent.server";
import type { WorkflowProgress } from "#/features/participation/schema";
export const WORKFLOW_LIMITS = Object.freeze({
  modelCalls: 24,
  toolCalls: 36,
  tokens: 100000,
  milliseconds: 120000,
  historyBytes: 100000,
});
export class BudgetExceeded extends Error {
  constructor() {
    super("Shared workflow budget or deadline exhausted");
  }
}
export class SharedBudget {
  constructor(
    readonly progress: WorkflowProgress,
    readonly signal: AbortSignal,
    readonly checkpoint: () => Promise<void>
  ) {}
  tool(count = 1) {
    if (this.signal.aborted || this.progress.toolCalls + count > WORKFLOW_LIMITS.toolCalls)
      throw new BudgetExceeded();
    this.progress.toolCalls += count;
  }
  wrap(driver: Driver): Driver {
    return {
      estimateTokens: history => driver.estimateTokens(history),
      next: (history, signal) => this.call(driver, history, signal),
    };
  }
  async call(driver: Driver, history: HistoryItem[], signal: AbortSignal): Promise<ModelTurn> {
    if (
      signal.aborted ||
      this.signal.aborted ||
      this.progress.modelCalls >= WORKFLOW_LIMITS.modelCalls ||
      this.progress.tokens + driver.estimateTokens(history) > WORKFLOW_LIMITS.tokens ||
      new TextEncoder().encode(JSON.stringify(history)).length > WORKFLOW_LIMITS.historyBytes
    )
      throw new BudgetExceeded();
    this.progress.modelCalls++;
    await this.checkpoint();
    const result = await driver.next(history, signal);
    if (!Number.isSafeInteger(result.tokens) || result.tokens < 0)
      throw new Error("Invalid provider usage");
    this.progress.tokens += result.tokens;
    if (result.usageKind === "estimated") this.progress.usageKind = "includes_estimates";
    await this.checkpoint();
    this.signal.throwIfAborted();
    if (this.progress.tokens > WORKFLOW_LIMITS.tokens) throw new BudgetExceeded();
    return result;
  }
}

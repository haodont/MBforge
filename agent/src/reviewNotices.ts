export interface ReviewNotice {
  reviewId: string
  content: string
  details: Record<string, unknown>
  /** Transient warning delivered together with the review notice. */
  warning?: string
}

/**
 * Background reviews finish on their own schedule; the foreground goal owns
 * the conversation. Hold notices while a goal is active and release them at the
 * next settled point after it ends.
 */
export class ReviewNoticeQueue {
  private pending: ReviewNotice[] = []

  enqueue(notice: ReviewNotice): void {
    this.pending.push(notice)
  }

  /** Drop a held notice whose review is being retried. */
  remove(reviewId: string): void {
    this.pending = this.pending.filter((notice) => notice.reviewId !== reviewId)
  }

  /** Pop notices only when no foreground goal owns the session. */
  drain(activeGoal: boolean): ReviewNotice[] {
    if (activeGoal) return []
    return this.pending.splice(0)
  }

  get size(): number {
    return this.pending.length
  }
}

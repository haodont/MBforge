/** Small async concurrency helpers. */

/** Run `worker` over `items` with at most `limit` calls in flight at a time. */
export async function runWithConcurrency<T>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<void>,
): Promise<void> {
  let next = 0
  const runners = Array.from(
    { length: Math.max(1, Math.min(limit, items.length)) },
    async () => {
      while (next < items.length) {
        const index = next
        next += 1
        await worker(items[index], index)
      }
    },
  )
  await Promise.all(runners)
}

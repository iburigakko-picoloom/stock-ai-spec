/** Stop scheduling work after a retained settings panel becomes hidden.
 * Android's local interpreter serializes requests; web requests stay parallel. */
export async function visibleReads(
  reads: (() => Promise<void>)[], active: () => boolean, serial: boolean, onError: () => void,
): Promise<boolean> {
  let failed = false;
  const run = async (read: () => Promise<void>) => {
    if (!active()) return;
    try { await read(); }
    catch { failed = true; if (active()) onError(); }
  };
  if (serial) {
    for (const read of reads) {
      if (!active()) return false;
      await run(read);
    }
  } else await Promise.all(reads.map(run));
  return active() && !failed;
}

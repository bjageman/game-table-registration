import { api, mutationOptions, type EventRecord } from "./api";

export interface CleanupProgress extends EventRecord {
  discord_cleanup_remaining: number;
  discord_cleanup_retry_after: number;
  discord_cleanup_error: string | null;
}

export async function finishDiscordCleanup(
  eventId: string, csrf: string, onProgress: (progress: CleanupProgress) => void,
  initial?: CleanupProgress,
): Promise<CleanupProgress> {
  let progress = initial;
  const deadline = Date.now() + 120000;
  if (progress) onProgress(progress);
  for (;;) {
    if (progress?.discord_cleanup_error) throw new Error(progress.discord_cleanup_error);
    if (progress && progress.discord_cleanup_remaining === 0) return progress;
    if (Date.now() >= deadline)
      throw new Error("Discord cleanup is still in progress. Show Archived to resume it later.");
    const retryAfter = progress?.discord_cleanup_retry_after ?? 0;
    if (retryAfter) {
      await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
    }
    progress = await api<CleanupProgress>(
      `/events/${encodeURIComponent(eventId)}/discord-messages/delete`, mutationOptions(csrf),
    );
    if (!Number.isInteger(progress.discord_cleanup_remaining) || progress.discord_cleanup_remaining < 0)
      throw new Error("Discord cleanup returned an invalid response. Refresh before retrying.");
    onProgress(progress);
  }
}

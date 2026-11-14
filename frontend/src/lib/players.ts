export interface PlayerSummary {
  discord_id: string;
  discord_name: string;
  real_name: string;
}

export function matchesPlayer(player: PlayerSummary, query: string): boolean {
  return `${player.discord_name} ${player.real_name} ${player.discord_id}`
    .toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}

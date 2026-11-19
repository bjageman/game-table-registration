export function ChecklistPlayer({ player, entry, onChange, controlId, disabled = false }: {
  player: { id: string; name: string };
  entry?: { arrived: boolean };
  onChange: (change: Partial<{ arrived: boolean }>) => void;
  controlId: string;
  disabled?: boolean;
}) {
  return <li>
    <div className="public-checklist-player">
      <label className="public-checklist-name" htmlFor={`${controlId}-arrived`}>
        <span className="public-checklist-checkbox">
          <input id={`${controlId}-arrived`} type="checkbox" disabled={disabled} checked={entry?.arrived ?? false}
            aria-label={`Mark ${player.name} as arrived`} onChange={(event) => onChange({ arrived: event.target.checked })} />
        </span>
        <span className="truncate-name" title={player.name}>{player.name}</span>
      </label>
    </div>
  </li>;
}

import { FormField } from "../../../components/FormFields";

export const DEFAULT_WARNING_MESSAGE = "Signups close soon! Don't forget to sign up.";

export function warningErrors(enabled: boolean, hours: string): Record<string, string> {
  const number = Number(hours);
  return enabled && (!Number.isInteger(number) || number < 1 || number > 767)
    ? { warning_hours_before_close: "Choose whole hours before close from 1 to 767." } : {};
}

export default function SignupWarningFields({ enabled, hours, message, onEnabled, onHours, onMessage, error }: {
  enabled: boolean; hours: string; message: string;
  onEnabled: (value: boolean) => void; onHours: (value: string) => void; onMessage: (value: string) => void;
  error?: string;
}) {
  return <div className="signup-warning-fields">
    <label className="scheduled-event-checkbox"><input id="event-post-warning-message" type="checkbox" checked={enabled}
      onChange={(event) => onEnabled(event.target.checked)} /> Post Warning Message</label>
    {enabled && <div className="form-grid">
      <FormField id="event-form-warning_hours_before_close" label="Hours before close" type="number" value={hours}
        onChange={(event) => onHours(event.target.value)} error={Boolean(error)} helperText={error}
        slotProps={{ htmlInput: { min: 1, max: 767, step: 1 } }} />
      <FormField id="event-form-warning-message" label="Warning message" value={message} placeholder={DEFAULT_WARNING_MESSAGE}
        onChange={(event) => onMessage(event.target.value)} multiline minRows={2}
        slotProps={{ htmlInput: { maxLength: 1600 } }} />
    </div>}
  </div>;
}

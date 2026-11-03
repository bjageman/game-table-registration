import type { ReactNode } from "react";
import TextField, { type TextFieldProps } from "@mui/material/TextField";

/** Own vertical spacing here, rather than adding margins to individual controls. */
export default function FormFields({ children }: { children: ReactNode }) {
  return <div className="form-fields">{children}</div>;
}

/** Shared defaults for full-width, outlined fields with persistent labels. */
export function FormField(props: TextFieldProps) {
  return <TextField fullWidth variant="outlined" {...props} margin="none"
    slotProps={{ ...props.slotProps, inputLabel: props.slotProps?.inputLabel ?? { shrink: true } }} />;
}

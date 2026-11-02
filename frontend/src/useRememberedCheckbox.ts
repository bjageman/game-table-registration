import { useState } from "react";

export default function useRememberedCheckbox(key: string): [boolean, (value: boolean) => void] {
  const [checked, setChecked] = useState(() => {
    try { return window.localStorage.getItem(key) === "true"; }
    catch { return false; }
  });
  function remember(value: boolean) {
    setChecked(value);
    try { window.localStorage.setItem(key, String(value)); }
    catch { /* The current browser may block local storage. */ }
  }
  return [checked, remember];
}

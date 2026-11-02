import { useEffect, useId, useRef } from "react";
import { isBackdropClick } from "./dialogBackdrop";
import type { EventTemplateRecord } from "./api";

export default function TemplatePicker({ templates, onSelect, onClose }: {
  templates: EventTemplateRecord[];
  onSelect: (template: EventTemplateRecord) => void;
  onClose: () => void;
}) {
  const heading = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const modal = dialog.current;
    const trigger = document.activeElement;
    modal?.showModal();
    return () => {
      modal?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);
  return <dialog ref={dialog} aria-labelledby={heading}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (isBackdropClick(event)) onClose(); }}>
    <h2 id={heading}>Load From Template</h2>
    <p>Choose a template to fill the title, signup duration, and tables. Your event date stays as it is.</p>
    <ul className="template-list">
      {templates.map((template) => <li key={template.id}>
        <button type="button" onClick={() => onSelect(template)}>
          <strong>{template.title}</strong>
          <span>{template.duration_hours} hours · {template.tables.length} {template.tables.length === 1 ? "table" : "tables"}</span>
          <small>{template.tables.map((table) => `${table.name} (${table.capacity})`).join(" · ")}</small>
        </button>
      </li>)}
    </ul>
    <div className="form-actions"><button type="button" onClick={onClose}>Cancel</button></div>
  </dialog>;
}

import ModalHeader from "../../../components/ModalHeader";
import { useEffect, useId, useRef } from "react";
import { isBackdropClick } from "../../../lib/dialogBackdrop";
import type { EventTemplateRecord } from "../../../lib/api";
import { X } from "lucide-react";

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
  return <dialog id="event-template-picker-dialog" ref={dialog} aria-labelledby={heading}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (isBackdropClick(event)) onClose(); }}>
    <ModalHeader>
      <h2 id={heading}>Load From Template</h2>
      <button id="event-template-picker-close-button" type="button" aria-label="Close template picker" title="Close" onClick={onClose}><X size={18} aria-hidden="true" /></button>
    </ModalHeader>
    <p>Choose a template to fill the title, signup duration, and tables. Your event date stays as it is.</p>
    <ul className="template-list">
      {templates.map((template) => <li key={template.id}>
        <button id={`event-template-select-${template.id}`} type="button" onClick={() => onSelect(template)}>
          <strong>{template.title}</strong>
          <span>{template.duration_hours} hours · {template.tables.length} {template.tables.length === 1 ? "table" : "tables"}</span>
          <small>{template.tables.map((table) => `${table.name} (${table.capacity})`).join(" · ")}</small>
        </button>
      </li>)}
    </ul>
    <div className="form-actions"><button id="event-template-picker-cancel-button" type="button" onClick={onClose}>Cancel</button></div>
  </dialog>;
}

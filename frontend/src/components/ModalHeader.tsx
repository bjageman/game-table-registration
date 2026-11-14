import { useRef, type ReactNode } from "react";
import useFittedText from "../hooks/useFittedText";

export default function ModalHeader({ children, className = "" }: {
  children: ReactNode;
  className?: string;
}) {
  const header = useRef<HTMLDivElement>(null);
  useFittedText(header, children, "h2");
  return <div ref={header} className={`event-modal-header ${className}`.trim()}>{children}</div>;
}

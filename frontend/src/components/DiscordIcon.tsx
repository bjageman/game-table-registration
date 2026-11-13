import type { SVGProps } from "react";

interface DiscordIconProps extends SVGProps<SVGSVGElement> {
  size?: number;
}

export function DiscordIcon({ size = 24, className, ...props }: DiscordIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
      {...props}
    >
      <path d="M19.27 5.33A16.4 16.4 0 0 0 15.23 4c-.2.35-.4.8-.55 1.17a15.3 15.3 0 0 0-4.36 0A11 11 0 0 0 9.76 4a16.5 16.5 0 0 0-4.05 1.34C3.13 9.2 2.44 12.97 2.79 16.7a16.6 16.6 0 0 0 5.02 2.54c.4-.55.77-1.14 1.08-1.76-.6-.22-1.16-.5-1.7-.82.14-.1.28-.22.42-.33a11.85 11.85 0 0 0 10.15 0c.14.12.28.23.42.33-.54.32-1.1.6-1.7.82.31.62.67 1.21 1.08 1.76a16.55 16.55 0 0 0 5.02-2.54c.42-4.33-.68-8.06-2.31-11.37ZM8.68 14.43c-.98 0-1.79-.9-1.79-2.01s.79-2.02 1.79-2.02 1.8.91 1.79 2.02c0 1.11-.79 2.01-1.79 2.01Zm6.64 0c-.98 0-1.79-.9-1.79-2.01s.79-2.02 1.79-2.02 1.8.91 1.79 2.02c0 1.11-.78 2.01-1.79 2.01Z" />
    </svg>
  );
}

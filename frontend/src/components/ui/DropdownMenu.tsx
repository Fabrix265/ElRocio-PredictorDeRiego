import * as Menu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({
  children,
  align = "end",
  className,
}: {
  children: ReactNode;
  align?: "start" | "center" | "end";
  className?: string;
}) {
  return (
    <Menu.Portal>
      <Menu.Content
        align={align}
        sideOffset={6}
        collisionPadding={8}
        className={cn(
          "z-50 min-w-[200px] overflow-hidden rounded-lg border border-borde bg-superficie p-1 shadow-elevada",
          className,
        )}
      >
        {children}
      </Menu.Content>
    </Menu.Portal>
  );
}

export function DropdownMenuItem({
  children,
  icono,
  peligro,
  disabled,
  onSelect,
}: {
  children: ReactNode;
  icono?: ReactNode;
  peligro?: boolean;
  disabled?: boolean;
  onSelect?: () => void;
}) {
  return (
    <Menu.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-[13.5px] outline-none select-none [&_svg]:size-4 [&_svg]:shrink-0",
        "data-[disabled]:cursor-not-allowed data-[disabled]:text-texto-3",
        peligro
          ? "text-err-tx data-[highlighted]:bg-err-bg"
          : "text-texto data-[highlighted]:bg-activo-bg data-[highlighted]:text-activo-tx",
      )}
    >
      {icono}
      {children}
    </Menu.Item>
  );
}

export function DropdownMenuLabel({ children }: { children: ReactNode }) {
  return <Menu.Label className="px-2.5 py-2 text-xs text-texto-2">{children}</Menu.Label>;
}

export function DropdownMenuSeparator() {
  return <Menu.Separator className="my-1 h-px bg-borde" />;
}

import { toast, Toaster as Sonner } from "sonner";

/** Contenedor de notificaciones (una vez en la raíz de la app). */
export function Toaster() {
  return (
    <Sonner
      position="top-right"
      closeButton
      richColors={false}
      toastOptions={{
        style: {
          fontFamily: "var(--fuente)",
          border: "1px solid var(--borde)",
          borderRadius: "var(--radio-lg)",
          boxShadow: "var(--sombra-lg)",
          background: "var(--superficie)",
          color: "var(--texto)",
        },
        classNames: {
          success: "[&_[data-icon]]:text-ok",
          error: "[&_[data-icon]]:text-err",
          description: "text-texto-2!",
        },
      }}
    />
  );
}

export const notificar = {
  exito: (mensaje: string, descripcion?: string) => toast.success(mensaje, { description: descripcion }),
  error: (mensaje: string, descripcion?: string) => toast.error(mensaje, { description: descripcion }),
  info: (mensaje: string, descripcion?: string) => toast(mensaje, { description: descripcion }),
};

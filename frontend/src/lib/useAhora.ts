import { useEffect, useState } from "react";

/** Hora actual que se renueva cada minuto (la fecha de Lima cambia sola a medianoche). */
export function useAhora(): Date {
  const [ahora, setAhora] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setAhora(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  return ahora;
}

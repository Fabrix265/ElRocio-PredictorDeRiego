import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  environment: string;
};

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/health")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json() as Promise<HealthResponse>;
      })
      .then(setHealth)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Error desconocido");
      });
  }, []);

  return (
    <main
      style={{
        minHeight: "100vh",
        margin: 0,
        display: "grid",
        placeItems: "center",
        background: "#f3f7f1",
        color: "#1f2d1f",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <section
        style={{
          width: "min(560px, 90vw)",
          padding: "2rem",
          borderRadius: "16px",
          background: "#ffffff",
          boxShadow: "0 18px 50px rgba(31, 45, 31, 0.12)",
        }}
      >
        <p style={{ margin: 0, color: "#4d7c4d", fontWeight: 700 }}>
          El Rocio
        </p>
        <h1 style={{ margin: "0.5rem 0 1rem", fontSize: "1.75rem" }}>
          Sistema de prediccion de riego
        </h1>
        <p style={{ margin: 0, lineHeight: 1.6 }}>
          Base del panel web para consultar predicciones de riego a partir de
          datos historicos de sensores y APIs.
        </p>
        <div
          style={{
            marginTop: "1.5rem",
            padding: "1rem",
            borderRadius: "12px",
            background: "#eef5ec",
          }}
        >
          <strong>API: </strong>
          {health
            ? `${health.status} (${health.environment})`
            : error
              ? `sin conexion (${error})`
              : "consultando..."}
        </div>
      </section>
    </main>
  );
}

import { useEffect, useState } from "react";

function App() {
  const [telemetry, setTelemetry] = useState({});

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const response = await fetch(
          "http://localhost:8080/latest"
        );

        const data = await response.json();

        setTelemetry(data);

      } catch (error) {
        console.error(error);
      }
    }, 500);

    return () => clearInterval(timer);

  }, []);

  return (
    <div style={{ padding: "20px" }}>
      <h1>Motorcycle Telemetry Dashboard</h1>

      <pre>
        {JSON.stringify(telemetry, null, 2)}
      </pre>
    </div>
  );
}

export default App;
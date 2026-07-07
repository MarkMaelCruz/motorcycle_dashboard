import { useEffect, useState } from "react";

function App() {
  const [telemetry, setTelemetry] = useState({});

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const response = await fetch(
          "https://motorcycle-telemetry-backend-112434217886.asia-southeast1.run.app/latest"
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
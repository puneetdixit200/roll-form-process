import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import "./styles.css";
import VisualFlowerWorkspace from "./features/visual-flower/VisualFlowerWorkspace";

export default function App() {
  return <AuthGate><main><section id="Flower-Sequence-Prototype" className="panel">
    <VisualFlowerWorkspace />
  </section></main></AuthGate>;
}

function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"checking" | "login" | "ready">("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/auth/status", { credentials: "same-origin" })
      .then((response) => response.json())
      .then((status) => setState(status.auth_enabled && !status.authenticated ? "login" : "ready"))
      .catch(() => setState("ready"));
  }, []);

  async function login(event: FormEvent) {
    event.preventDefault();
    setError("");
    const response = await fetch("/api/auth/login", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      setError("Login failed. Check the demo credentials.");
      return;
    }
    setPassword("");
    setState("ready");
  }

  if (state === "checking") return <main className="panel"><p>Checking demo access…</p></main>;
  if (state === "login") return <main className="panel auth-panel"><h1>Visual Flower Generator</h1><p>This private customer demo requires authentication.</p><form onSubmit={login}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>{error && <p role="alert">{error}</p>}<button type="submit">Sign in</button></form></main>;
  return <>{children}</>;
}
